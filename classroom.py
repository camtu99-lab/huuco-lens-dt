"""Lớp học: tài khoản học sinh (mã lớp + PIN), bài giáo viên giao, bài nộp và thống kê.

Không dùng streamlit để dễ kiểm thử. Dữ liệu nằm trong các bảng chung của history_store
(Google Sheets nếu đã cấu hình, ngược lại tệp JSON trong data/tables/).

Bảng:
  classes      ma_lop, ten_lop, tao_luc
  accounts     ma_lop, hoc_sinh, salt, pin_hash, tao_luc
  assignments  id, ma_lop, tieu_de, tao_luc, han_nop, cau_hoi_json, cho_goi_y
  attachments  id_bai, ma_lop, ten, loai (file|link), kich_thuoc, phan, du_lieu  (file chia nhỏ base64, mỗi dòng một phần)
  submissions  id_bai, ma_lop, hoc_sinh, thoi_diem, cau, dang, chu_de, bai_lam, ket_qua, so_lan, goi_y
Mỗi câu hỏi được mô tả bằng {"k": "draw" | "name", "n": tên chất trong ngân hàng đề}, khóa câu là "draw:etanol".
"""
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import time

import history_store as hs

CLASSES_H = ["ma_lop", "ten_lop", "tao_luc"]
ACC_H = ["ma_lop", "hoc_sinh", "salt", "pin_hash", "tao_luc"]
ASG_H = ["id", "ma_lop", "tieu_de", "tao_luc", "han_nop", "cau_hoi_json", "cho_goi_y"]
ATT_H = ["id_bai", "ma_lop", "ten", "loai", "kich_thuoc", "phan", "du_lieu"]
MAX_FILE = 1_000_000      # byte mỗi tệp đính kèm
MAX_ATT = 5               # số tệp/liên kết tối đa mỗi bài
CHUNK = 40_000            # ký tự base64 mỗi ô (Google Sheets giới hạn 50.000)
SUB_H = ["id_bai", "ma_lop", "hoc_sinh", "thoi_diem", "cau", "dang", "chu_de", "bai_lam", "ket_qua", "so_lan", "goi_y"]
TOKEN_DAYS = 14
PIN_ROUNDS = 120_000
TEACHER = "teacher"
STUDENT = "student"
NAME_RE = re.compile(r"^[^\W\d_](?:[\w .'\-]*[^\W_])?$", re.UNICODE)   # chữ cái (có dấu), số, khoảng trắng, . ' -


class Denied(Exception):
    """Người dùng không có quyền với dữ liệu được yêu cầu."""


def norm_code(code):
    """Mã lớp viết hoa, bỏ khoảng trắng; rỗng nếu không hợp lệ (2-20 ký tự chữ số - _)."""
    c = re.sub(r"\s+", "", str(code or "")).upper()
    return c if re.fullmatch(r"[A-Z0-9_\-]{2,20}", c) else ""


def identity(code, name):
    """Tên dùng làm khóa lịch sử: 'An [10A1]' (hai lớp có thể trùng tên mà không lẫn)."""
    return f"{name.strip()} [{code}]"


def qkey(q):
    return f'{q["k"]}:{q["n"]}'


# ---------------- Danh tính và phân quyền ----------------
def clean_name(name):
    return re.sub(r"\s+", " ", str(name or "")).strip()[:40]


def valid_name(name):
    """Họ tên 2-40 ký tự: chữ cái (có dấu), số, khoảng trắng, dấu chấm, nháy, gạch nối."""
    n = clean_name(name)
    return len(n) >= 2 and bool(NAME_RE.match(n)) and bool(hs.slug(n))


def uid(code, name):
    """Mã định danh duy nhất của học sinh: mã lớp + tên không dấu (VD '10A1:nguyen_van_an')."""
    return f"{norm_code(code)}:{hs.slug(name)}"


def make_auth(role, code="", name=""):
    """Phiên đăng nhập. 'key' là khóa lưu lịch sử/bài nộp (cùng định dạng cũ 'Tên [LỚP]')."""
    if role == TEACHER:
        return {"role": TEACHER, "cls": "", "name": "", "uid": "teacher", "key": ""}
    return {"role": STUDENT, "cls": norm_code(code), "name": name, "uid": uid(code, name), "key": identity(norm_code(code), name)}


def is_teacher(auth):
    return bool(auth) and auth.get("role") == TEACHER


def is_student(auth):
    return bool(auth) and auth.get("role") == STUDENT and bool(auth.get("key"))


def _need_teacher(auth):
    if not is_teacher(auth):
        raise Denied("Chỉ giáo viên được thực hiện thao tác này.")


def _need_own(auth, key):
    """Học sinh chỉ được đụng vào dữ liệu của chính mình; giáo viên không ghi vào hồ sơ học sinh."""
    if not is_student(auth) or hs.slug(key) != hs.slug(auth["key"]) or not key:
        raise Denied("Không có quyền với dữ liệu của học sinh khác.")


def check_teacher_code(entered, expected):
    """So sánh mã giáo viên theo thời gian không đổi; chưa cấu hình mã thì không ai là giáo viên."""
    if not expected or not entered:
        return False
    return hmac.compare_digest(str(entered).encode(), str(expected).encode())


# ---------------- Lớp (chỉ giáo viên được tạo/xóa/liệt kê) ----------------
def _classes(force=False):
    return [(r[0], r[1] if len(r) > 1 else r[0]) for r in hs.tbl_read("classes", CLASSES_H, force=force) if r and r[0]]


def classes(auth, force=False):
    _need_teacher(auth)
    return _classes(force)


def class_exists(code, force=False):
    """Kiểm tra mã lớp có tồn tại (dùng cho đăng nhập, không lộ danh sách lớp)."""
    c = norm_code(code)
    return bool(c) and any(x[0] == c for x in _classes(force))


def create_class(auth, code, name, now):
    _need_teacher(auth)
    c = norm_code(code)
    if not c or class_exists(c, force=True):
        return False
    hs.tbl_append("classes", CLASSES_H, [c, (name or c).strip(), now])
    return True


def delete_class(auth, code):
    """Xóa lớp cùng tài khoản, bài giao và bài nộp của lớp."""
    _need_teacher(auth)
    c = norm_code(code)
    for name, head, col in (("classes", CLASSES_H, 0), ("accounts", ACC_H, 0), ("assignments", ASG_H, 1), ("submissions", SUB_H, 1)):
        rows = hs.tbl_read(name, head, force=True)
        keep = [r for r in rows if (r + [""] * 3)[col] != c]
        if len(keep) != len(rows):
            hs.tbl_write(name, head, keep)


# ---------------- Tài khoản học sinh ----------------
def hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", str(pin).encode("utf-8"), salt.encode("utf-8"), PIN_ROUNDS).hex()


def _find_account(c, name):
    sl = hs.slug(name)
    for r in hs.tbl_read("accounts", ACC_H, force=True):
        if len(r) >= 4 and r[0] == c and hs.slug(r[1]) == sl:
            return r
    return None


def _check_input(code, name, pin):
    """Kiểm tra dữ liệu nhập. Trả về (trạng thái lỗi hoặc '', mã lớp chuẩn, tên chuẩn, pin)."""
    c, n, p = norm_code(code), clean_name(name), str(pin or "").strip()
    if not c:
        return "bad_code", c, n, p
    if not valid_name(n):
        return "bad_name", c, n, p
    if len(p) < 4 or len(p) > 12:
        return "bad_pin", c, n, p
    return "", c, n, p


def login(code, name, pin):
    """Đăng nhập lại. Trả về (trạng thái, tên chuẩn). Trạng thái: ok | wrong | no_account | no_class | bad_code | bad_name | bad_pin.
    Không bao giờ tạo tài khoản mới."""
    err, c, n, p = _check_input(code, name, pin)
    if err:
        return err, n
    if not class_exists(c, force=True):
        return "no_class", n
    r = _find_account(c, n)
    if not r:
        return "no_account", n
    return ("ok" if hmac.compare_digest(hash_pin(p, r[2]), r[3]) else "wrong"), r[1]


def register(code, name, pin, pin2, now):
    """Đăng ký lần đầu. Trạng thái: new | exists | mismatch | no_class | bad_code | bad_name | bad_pin.
    Một tên (không phân biệt hoa/thường/dấu) chỉ có một tài khoản trong lớp."""
    err, c, n, p = _check_input(code, name, pin)
    if err:
        return err, n
    if str(pin2 or "").strip() != p:
        return "mismatch", n
    if not class_exists(c, force=True):
        return "no_class", n
    old = _find_account(c, n)
    if old:
        return "exists", old[1]
    salt = secrets.token_hex(8)
    hs.tbl_append("accounts", ACC_H, [c, n, salt, hash_pin(p, salt), now])
    # Hai máy đăng ký cùng lúc: chỉ giữ dòng đến trước.
    sl = hs.slug(n)
    same = [r for r in hs.tbl_read("accounts", ACC_H, force=True) if len(r) >= 4 and r[0] == c and hs.slug(r[1]) == sl]
    if len(same) > 1 and same[0][2] != salt:
        rows = hs.tbl_read("accounts", ACC_H, force=True)
        hs.tbl_write("accounts", ACC_H, [r for r in rows if not (len(r) >= 4 and r[0] == c and r[2] == salt)])
        return "exists", same[0][1]
    return "new", n


def change_pin(auth, old_pin, new_pin, new_pin2):
    """Học sinh tự đổi PIN của mình. Trả về ok | wrong | bad_pin | mismatch."""
    if not is_student(auth):
        raise Denied("Cần đăng nhập học sinh.")
    new_pin = str(new_pin or "").strip()
    if len(new_pin) < 4 or len(new_pin) > 12:
        return "bad_pin"
    if str(new_pin2 or "").strip() != new_pin:
        return "mismatch"
    rows = hs.tbl_read("accounts", ACC_H, force=True)
    sl = hs.slug(auth["name"])
    for i, r in enumerate(rows):
        if len(r) >= 4 and r[0] == auth["cls"] and hs.slug(r[1]) == sl:
            if not hmac.compare_digest(hash_pin(str(old_pin or "").strip(), r[2]), r[3]):
                return "wrong"
            salt = secrets.token_hex(8)
            rows[i] = [r[0], r[1], salt, hash_pin(new_pin, salt)] + list(r[4:])
            hs.tbl_write("accounts", ACC_H, rows)
            return "ok"
    return "wrong"


def students(auth, code):
    _need_teacher(auth)
    c = norm_code(code)
    return sorted({r[1] for r in hs.tbl_read("accounts", ACC_H) if len(r) > 1 and r[0] == c}, key=str.lower)


def reset_pin(auth, code, name):
    """Xóa tài khoản để học sinh đăng ký lại với PIN mới (lịch sử và bài nộp vẫn giữ)."""
    _need_teacher(auth)
    c, sl = norm_code(code), hs.slug(name)
    rows = hs.tbl_read("accounts", ACC_H, force=True)
    keep = [r for r in rows if not (len(r) > 1 and r[0] == c and hs.slug(r[1]) == sl)]
    if len(keep) != len(rows):
        hs.tbl_write("accounts", ACC_H, keep)
        return True
    return False


# ---------------- Mã đăng nhập tự động (giữ đăng nhập khi tải lại trang) ----------------
def _salt_of(code, name):
    sl = hs.slug(name)
    for r in hs.tbl_read("accounts", ACC_H):
        if len(r) >= 4 and r[0] == code and hs.slug(r[1]) == sl:
            return r[2][:8]
    return ""


def make_token(key, code, name, ts=None):
    """Mã ký (không chứa PIN) gắn với muối của tài khoản: đổi hoặc đặt lại PIN thì mã cũ hết hiệu lực."""
    payload = f"{code}|{name}|{int(ts or time.time())}|{_salt_of(code, name)}"
    sig = hmac.new(str(key).encode(), payload.encode(), hashlib.sha256).hexdigest()[:24]
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=") + "." + sig


def verify_token(key, token, now=None):
    """Trả về (mã lớp, tên) nếu mã hợp lệ, chưa quá hạn và tài khoản (cùng PIN) còn nguyên; ngược lại None."""
    try:
        b, sig = str(token).split(".", 1)
        payload = base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)).decode()
        good = hmac.new(str(key).encode(), payload.encode(), hashlib.sha256).hexdigest()[:24]
        code, name, ts, salt = payload.split("|")
        if not hmac.compare_digest(sig, good) or (now or time.time()) - int(ts) > TOKEN_DAYS * 86400:
            return None
        if salt and salt == _salt_of(code, name):
            return code, name
    except Exception:
        pass
    return None


# ---------------- Bài giao ----------------
def create_assignment(auth, code, title, questions, due, hints, now):
    _need_teacher(auth)
    aid = secrets.token_hex(4)
    hs.tbl_append("assignments", ASG_H, [aid, norm_code(code), title.strip()[:100], now, due or "",
                                         json.dumps(questions, ensure_ascii=False), "1" if hints else "0"])
    return aid


def assignments(auth, code):
    """Bài giao của lớp, mới nhất trước. Giáo viên xem mọi lớp, học sinh chỉ xem lớp của mình."""
    if not is_teacher(auth) and not (is_student(auth) and auth["cls"] == norm_code(code)):
        raise Denied("Không có quyền xem bài giao của lớp này.")
    out = []
    for r in hs.tbl_read("assignments", ASG_H):
        if len(r) >= 7 and r[1] == norm_code(code):
            try:
                qs = json.loads(r[5])
            except ValueError:
                qs = []
            out.append({"id": r[0], "code": r[1], "title": r[2], "created": r[3], "due": r[4], "questions": qs, "hints": r[6] == "1"})
    return sorted(out, key=lambda a: a["created"], reverse=True)


def delete_assignment(auth, aid):
    _need_teacher(auth)
    for name, head, col in (("assignments", ASG_H, 0), ("attachments", ATT_H, 0), ("submissions", SUB_H, 0)):
        rows = hs.tbl_read(name, head, force=True)
        keep = [r for r in rows if (r + [""])[col] != aid]
        if len(keep) != len(rows):
            hs.tbl_write(name, head, keep)


# ---------------- Tài liệu đính kèm bài giao ----------------
def add_attachments(auth, aid, code, files=(), links=()):
    """files: [(tên, bytes)], links: [(nhãn, url)]. Chỉ giáo viên. Trả về số mục đã lưu."""
    _need_teacher(auth)
    code = norm_code(code)
    if len(files) + len(links) > MAX_ATT:
        raise ValueError(f"Tối đa {MAX_ATT} tệp/liên kết cho mỗi bài.")
    rows = []
    for name, data in files:
        name = os.path.basename(str(name)).strip()[:100] or "tai-lieu"
        if len(data) > MAX_FILE:
            raise ValueError(f"Tệp {name} lớn hơn {MAX_FILE // 1_000_000} MB. Hãy dán liên kết Google Drive thay vì tải lên.")
        b64 = base64.b64encode(data).decode()
        for i in range(0, max(1, len(b64)), CHUNK):
            rows.append([aid, code, name, "file", len(data), i // CHUNK, b64[i:i + CHUNK]])
    for label, url in links:
        url = str(url).strip()
        if not re.match(r"^https?://\S+$", url):
            raise ValueError("Liên kết phải bắt đầu bằng http:// hoặc https://")
        rows.append([aid, code, (str(label).strip() or url)[:100], "link", 0, 0, url[:2000]])
    hs.tbl_append_many("attachments", ATT_H, rows)
    return len(files) + len(links)


def _att_rows(auth, code):
    if not is_teacher(auth) and not (is_student(auth) and auth["cls"] == norm_code(code)):
        raise Denied("Không có quyền xem tài liệu của lớp này.")
    return [r + [""] * (7 - len(r)) for r in hs.tbl_read("attachments", ATT_H) if len(r) >= 3 and r[1] == norm_code(code)]


def attachments(auth, code, aid, with_data=False):
    """Danh sách tài liệu của một bài: [{name, kind, size, url, data}]. data (bytes) chỉ giải mã khi with_data=True."""
    out, chunks = {}, {}
    for r in _att_rows(auth, code):
        if r[0] != aid:
            continue
        key = (r[2], r[3])
        if r[3] == "link":
            out[key] = {"name": r[2], "kind": "link", "size": 0, "url": r[6]}
        else:
            try:
                size = int(r[4] or 0)
                part = int(r[5] or 0)
            except ValueError:
                continue
            out.setdefault(key, {"name": r[2], "kind": "file", "size": size, "mime": mimetypes.guess_type(r[2])[0] or "application/octet-stream"})
            chunks.setdefault(key, {})[part] = r[6]
    res = []
    for key, it in out.items():
        if it["kind"] == "file" and with_data:
            parts = chunks.get(key, {})
            try:
                it["data"] = base64.b64decode("".join(parts[i] for i in sorted(parts)))
            except ValueError:
                it["data"] = b""
        res.append(it)
    return res


def attachment_counts(auth, code):
    """{id bài: số tài liệu} để hiện biểu tượng 📎 trong danh sách."""
    seen, cnt = set(), {}
    for r in _att_rows(auth, code):
        k = (r[0], r[2], r[3])
        if k not in seen:
            seen.add(k)
            cnt[r[0]] = cnt.get(r[0], 0) + 1
    return cnt


def delete_attachment(auth, code, aid, name):
    _need_teacher(auth)
    rows = hs.tbl_read("attachments", ATT_H, force=True)
    keep = [r for r in rows if not (len(r) >= 3 and r[0] == aid and r[1] == norm_code(code) and r[2] == name)]
    if len(keep) != len(rows):
        hs.tbl_write("attachments", ATT_H, keep)


# ---------------- Bài nộp ----------------
def add_submission(auth, aid, q, topic, given, result, attempt, hints, ts):
    """Chỉ học sinh đã đăng nhập mới ghi được bài nộp, và luôn ghi dưới tên chính mình."""
    if not is_student(auth):
        raise Denied("Cần đăng nhập học sinh để nộp bài.")
    hs.tbl_append("submissions", SUB_H, [aid or "", auth["cls"], auth["key"], ts, qkey(q), q["k"], topic, str(given)[:200],
                                         result, attempt, hints])


def submissions(auth, aid=None, code=None, student=None, force=False):
    """Giáo viên đọc mọi bài nộp; học sinh chỉ đọc bài nộp của chính mình (bị ép lọc theo tên mình)."""
    if is_student(auth):
        if (code and norm_code(code) != auth["cls"]) or (student and hs.slug(student) != hs.slug(auth["key"])):
            raise Denied("Không có quyền xem bài nộp của học sinh khác.")
        code, student = auth["cls"], auth["key"]
    elif not is_teacher(auth):
        raise Denied("Cần đăng nhập.")
    out = []
    for r in hs.tbl_read("submissions", SUB_H, force=force):
        r = r + [""] * (11 - len(r))
        if (aid is None or r[0] == aid) and (code is None or r[1] == norm_code(code)) and (student is None or hs.slug(r[2]) == hs.slug(student)):
            try:
                at, gy = int(r[9] or 1), int(r[10] or 0)
            except ValueError:
                at, gy = 1, 0
            out.append({"aid": r[0], "code": r[1], "student": r[2], "ts": r[3], "q": r[4], "kind": r[5], "topic": r[6],
                        "given": r[7], "result": r[8], "attempt": at, "hints": gy})
    return out


# ---------------- Lịch sử tra cứu (có kiểm tra quyền) ----------------
def read_history(auth, who):
    if is_teacher(auth):
        return hs.load(who)
    _need_own(auth, who)
    return hs.load(who)


def write_history(auth, who, items):
    _need_own(auth, who)
    hs.save(who, items)


def append_history(auth, who, entry):
    _need_own(auth, who)
    hs.append(who, entry)


def clear_history(auth, who, kinds=None):
    _need_own(auth, who)
    hs.clear(who, kinds) if kinds else hs.clear(who)


def touch_visit(auth, who, ts):
    _need_own(auth, who)
    hs.touch(who, ts)


def history_summary(auth, force=False):
    _need_teacher(auth)
    return hs.summary(force=force)


def delete_history(auth, who):
    _need_teacher(auth)
    hs.delete(who)


def progress(assignment, subs):
    """{học sinh: {khóa câu: {'ok': bool, 'first': bool, 'tries': n, 'hints': n}}} cho một bài giao."""
    keys = {qkey(q) for q in assignment["questions"]}
    out = {}
    for s in sorted(subs, key=lambda x: (x["ts"], x["attempt"])):
        if s["q"] not in keys:
            continue
        d = out.setdefault(s["student"], {}).setdefault(s["q"], {"ok": False, "first": False, "tries": 0, "hints": 0})
        d["tries"] += 1
        d["hints"] = max(d["hints"], s["hints"])
        if s["result"] == "dung" and not d["ok"]:
            d["ok"] = True
            d["first"] = d["tries"] == 1
    return out


def weak_spots(subs):
    """Thống kê chỗ hay sai: theo chủ đề và theo câu. Mỗi mục: lượt nộp, lượt sai, số học sinh sai, tỉ lệ sai (%)."""
    def agg(keyfn):
        d = {}
        for s in subs:
            k = keyfn(s)
            if not k:
                continue
            x = d.setdefault(k, {"n": 0, "wrong": 0, "wrong_students": set()})
            x["n"] += 1
            if s["result"] != "dung":
                x["wrong"] += 1
                x["wrong_students"].add(s["student"])
        rows = [{"key": k, "n": v["n"], "wrong": v["wrong"], "students": len(v["wrong_students"]),
                 "pct": round(100 * v["wrong"] / v["n"]) if v["n"] else 0} for k, v in d.items()]
        return sorted(rows, key=lambda r: (-r["pct"], -r["wrong"]))
    return {"topic": agg(lambda s: s["topic"]), "question": agg(lambda s: s["q"]),
            "kind": agg(lambda s: {"draw": "Vẽ công thức", "name": "Gọi tên"}.get(s["kind"], s["kind"]))}


def profile(subs, max_tries=3):
    """Thống kê thật từ bài nộp của một học sinh; chưa có bài nộp thì attempts = 0 và accuracy = None.
    done: số câu khác nhau đã làm · finished: số câu đã xong (đúng hoặc hết lượt thử) · solved: số câu đã đúng
    accuracy: % lượt nộp đúng · weak: chủ đề sai nhiều nhất · solved_keys: các câu đã đúng."""
    if not subs:
        return {"attempts": 0, "done": 0, "finished": 0, "solved": 0, "accuracy": None, "weak": [], "solved_keys": []}
    solved = {s["q"] for s in subs if s["result"] == "dung"}
    tries = {}
    for s in subs:
        tries[s["q"]] = max(tries.get(s["q"], 0), s["attempt"])
    finished = solved | {q for q, n in tries.items() if n >= max_tries}
    right = sum(1 for s in subs if s["result"] == "dung")
    by = {}
    for s in subs:
        if not s["topic"]:
            continue
        d = by.setdefault(s["topic"], {"n": 0, "wrong": 0})
        d["n"] += 1
        d["wrong"] += 0 if s["result"] == "dung" else 1
    weak = sorted(({"topic": t, "n": v["n"], "wrong": v["wrong"], "pct": round(100 * v["wrong"] / v["n"])} for t, v in by.items() if v["wrong"]),
                  key=lambda r: (-r["pct"], -r["wrong"], r["topic"]))
    return {"attempts": len(subs), "done": len(tries), "finished": len(finished), "solved": len(solved),
            "accuracy": round(100 * right / len(subs)), "weak": weak, "solved_keys": sorted(solved)}
