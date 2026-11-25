"""Lớp học: tài khoản học sinh (mã lớp + PIN), bài giáo viên giao, bài nộp và thống kê.

Không dùng streamlit để dễ kiểm thử. Dữ liệu nằm trong các bảng chung của history_store
(Google Sheets nếu đã cấu hình, ngược lại tệp JSON trong data/tables/).

Bảng:
  classes      ma_lop, ten_lop, tao_luc
  accounts     ma_lop, hoc_sinh, salt, pin_hash, tao_luc
  assignments  id, ma_lop, tieu_de, tao_luc, han_nop, cau_hoi_json, cho_goi_y
  submissions  id_bai, ma_lop, hoc_sinh, thoi_diem, cau, dang, chu_de, bai_lam, ket_qua, so_lan, goi_y
Mỗi câu hỏi được mô tả bằng {"k": "draw" | "name", "n": tên chất trong ngân hàng đề}, khóa câu là "draw:etanol".
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time

import history_store as hs

CLASSES_H = ["ma_lop", "ten_lop", "tao_luc"]
ACC_H = ["ma_lop", "hoc_sinh", "salt", "pin_hash", "tao_luc"]
ASG_H = ["id", "ma_lop", "tieu_de", "tao_luc", "han_nop", "cau_hoi_json", "cho_goi_y", "dang_bai", "phan_loai", "phut"]
SUB_H = ["id_bai", "ma_lop", "hoc_sinh", "thoi_diem", "cau", "dang", "chu_de", "bai_lam", "ket_qua", "so_lan", "goi_y"]
SHEET_H = ["id_bai", "ma_lop", "cau_hinh_json"]
STARTS_H = ["id_bai", "ma_lop", "hoc_sinh", "bat_dau"]
GRACE = 120                   # giây cho phép nộp muộn sau khi hết giờ (đồng hồ trình duyệt tự nộp có thể trễ)
TCH_H = ["ten", "salt", "ma_hash", "tao_luc"]
SSUB_H = ["id_bai", "ma_lop", "hoc_sinh", "thoi_diem", "tra_loi_json", "diem", "chi_tiet_json"]
TF_POINTS = {0: 0.0, 1: 0.1, 2: 0.25, 3: 0.5, 4: 1.0}   # thang điểm đúng/sai THPT: số ý đúng -> điểm
MC_POINT = SA_POINT = 0.25
FILE_H = ["id_tep", "id_bai", "ma_lop", "hoc_sinh", "loai", "ten_tep", "mime", "kich_thuoc", "tao_luc"]
DATA_H = ["id_tep", "stt", "du_lieu_base64"]
MAX_FILE = 1_000_000          # byte; tệp nằm trong ô Google Sheets nên giữ nhỏ
CHUNK = 45_000                # ký tự base64 mỗi ô (Sheets cho tối đa 50 000)
MAX_ATT = 5                   # số tệp đính kèm tối đa cho một bài giao
ALLOWED_EXT = {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv", "png", "jpg", "jpeg", "gif", "zip"}
IMG_EXT = {"png", "jpg", "jpeg"}
MAX_IMG_RAW = 20_000_000      # ảnh gốc tối đa 20 MB, sẽ được nén xuống dưới MAX_FILE
ATT, SUBF = "att", "sub"      # tệp giáo viên đính kèm / tệp học sinh nộp
TOKEN_DAYS = 14
PIN_ROUNDS = 120_000
PRACTICE = "practice"        # phân loại bài giao: luyện tập (có gợi ý) / kiểm tra
TEST = "test"
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


# ---------------- Tài khoản giáo viên tự tạo (bảng teachers: tên, muối, mã băm) ----------------
TCODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"      # bỏ O/0/I/1 cho dễ đọc


def gen_teacher_code():
    """Mã giáo viên ngẫu nhiên, dễ đọc: GV-XXXXXX."""
    return "GV-" + "".join(secrets.choice(TCODE_ALPHABET) for _ in range(6))


def clean_tcode(code):
    return str(code or "").strip()


def valid_tcode(code):
    c = clean_tcode(code)
    return 6 <= len(c) <= 24 and not re.search(r"\s", c)


def _teacher_rows():
    return [r for r in hs.tbl_read("teachers", TCH_H, force=True) if len(r) >= 3 and r[1] and r[2]]


def register_teacher(name, code, code2, now, master=""):
    """Giáo viên chưa có mã tự tạo mã của mình. Trạng thái: new | bad_name | bad_tcode | mismatch | taken.
    Mã được băm (PBKDF2) rồi mới lưu, không lưu mã gốc."""
    n, c = clean_name(name), clean_tcode(code)
    if not valid_name(n):
        return "bad_name"
    if not valid_tcode(c):
        return "bad_tcode"
    if clean_tcode(code2) != c:
        return "mismatch"
    if master and check_teacher_code(c, master):
        return "taken"
    for r in _teacher_rows():
        if hmac.compare_digest(hash_pin(c, r[1]), r[2]):
            return "taken"
    salt = secrets.token_hex(8)
    hs.tbl_append("teachers", TCH_H, [n, salt, hash_pin(c, salt), now])
    return "new"


def login_teacher(code):
    """Tên giáo viên nếu mã đúng, ngược lại None."""
    c = clean_tcode(code)
    if not c:
        return None
    for r in _teacher_rows():
        if hmac.compare_digest(hash_pin(c, r[1]), r[2]):
            return r[0]
    return None


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
    _purge_files(lambda r: r[2] == c)
    for name, head, col in (("classes", CLASSES_H, 0), ("accounts", ACC_H, 0), ("assignments", ASG_H, 1), ("submissions", SUB_H, 1),
                            ("sheets", SHEET_H, 1), ("sheetsubs", SSUB_H, 1), ("starts", STARTS_H, 1)):
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
def create_assignment(auth, code, title, questions, due, hints, now, kind="", cat=PRACTICE, minutes=0):
    _need_teacher(auth)
    aid = secrets.token_hex(4)
    hs.tbl_append("assignments", ASG_H, [aid, norm_code(code), title.strip()[:100], now, due or "",
                                         json.dumps(questions, ensure_ascii=False), "1" if hints else "0", clean_name(kind)[:40] if kind else "", TEST if cat == TEST else PRACTICE, str(max(0, min(int(minutes or 0), 300)))])
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
            out.append({"id": r[0], "code": r[1], "title": r[2], "created": r[3], "due": r[4], "questions": qs, "hints": r[6] == "1", "kind": r[7] if len(r) > 7 else "", "cat": TEST if len(r) > 8 and r[8] == TEST else PRACTICE,
                    "mins": int(r[9]) if len(r) > 9 and str(r[9]).isdigit() else 0})
    return sorted(out, key=lambda a: a["created"], reverse=True)


def guess_minutes(title):
    """Đoán số phút từ tên bài, ví dụ 'kt 15p', 'Kiểm tra 45 phút' -> 15, 45. Không thấy thì 0."""
    m = re.search(r"(?<!\d)(\d{1,3})\s*(?:phút|phut|min|ph|p)(?![A-Za-zÀ-ỹ])", str(title or ""), re.I)
    v = int(m.group(1)) if m else 0
    return v if 1 <= v <= 300 else 0


def set_assignment_minutes(auth, aid, minutes):
    """Giáo viên đặt/sửa thời gian làm bài (phút) của bài đã giao; 0 = không giới hạn."""
    _need_teacher(auth)
    m = str(max(0, min(int(minutes or 0), 300)))
    rows = hs.tbl_read("assignments", ASG_H, force=True)
    hit = False
    for r in rows:
        if r and r[0] == aid:
            r += [""] * (len(ASG_H) - len(r))
            r[9] = m
            hit = True
    if not hit:
        raise Denied("Không tìm thấy bài giao.")
    hs.tbl_write("assignments", ASG_H, rows)
    return int(m)


def delete_assignment(auth, aid):
    _need_teacher(auth)
    _purge_files(lambda r: r[1] == aid)
    for name, head, col in (("assignments", ASG_H, 0), ("submissions", SUB_H, 0), ("sheets", SHEET_H, 0), ("sheetsubs", SSUB_H, 0), ("starts", STARTS_H, 0)):
        rows = hs.tbl_read(name, head, force=True)
        keep = [r for r in rows if (r + [""])[col] != aid]
        if len(keep) != len(rows):
            hs.tbl_write(name, head, keep)


# ---------------- Tệp đính kèm & tệp nộp ----------------
def _pad(r, n=9):
    return r + [""] * (n - len(r))


def safe_name(name):
    n = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", (name or "").strip()).strip(". ")
    return n[-80:] or "tep"


def ext_of(name):
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def size_limit(name):
    """Dung lượng tối đa của tệp được chọn (ảnh được phép lớn hơn vì sẽ tự nén)."""
    return MAX_IMG_RAW if ext_of(name) in IMG_EXT else MAX_FILE


def shrink_image(name, data):
    """Nén ảnh png/jpg lớn xuống dưới MAX_FILE: xoay đúng chiều, thu nhỏ dần, lưu JPEG. Trả về (tên, dữ liệu, mime)."""
    from io import BytesIO
    from PIL import Image, ImageOps
    try:
        im = ImageOps.exif_transpose(Image.open(BytesIO(data)))
        im.load()
    except Exception:
        raise Denied("Không đọc được ảnh này.")
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    target = int(MAX_FILE * 0.9)
    side = 2000
    while True:
        w = im.copy()
        w.thumbnail((side, side))
        for q in (85, 75, 65, 55, 45):
            buf = BytesIO()
            w.save(buf, "JPEG", quality=q, optimize=True)
            if buf.tell() <= target:
                return name.rsplit(".", 1)[0] + ".jpg", buf.getvalue(), "image/jpeg"
        side = int(side * 0.75)
        if side < 400:
            raise Denied("Không nén được ảnh xuống đủ nhỏ.")


def _file_meta(r):
    r = _pad(r)
    try:
        size = int(r[7])
    except ValueError:
        size = 0
    return {"id": r[0], "aid": r[1], "code": r[2], "student": r[3], "kind": r[4], "name": r[5], "mime": r[6], "size": size, "ts": r[8]}


def _can_see(auth, m):
    if is_teacher(auth):
        return True
    if not is_student(auth) or m["code"] != auth["cls"]:
        return False
    return m["kind"] == ATT or hs.slug(m["student"]) == hs.slug(auth["key"])


def add_file(auth, aid, kind, name, mime, data, now):
    """Giáo viên đính kèm đề (kind=att) hoặc học sinh nộp bài làm (kind=sub). Trả về id tệp."""
    if kind == ATT:
        _need_teacher(auth)
        asg = next((a for a in _all_asg() if a[0] == aid), None)
        code, who = (asg[1] if asg else ""), ""
        if not asg:
            raise Denied("Không tìm thấy bài giao.")
        if sum(1 for r in hs.tbl_read("files", FILE_H, force=True) if _pad(r)[1] == aid and _pad(r)[4] == ATT) >= MAX_ATT:
            raise Denied(f"Mỗi bài chỉ đính kèm tối đa {MAX_ATT} tệp.")
    elif kind == SUBF:
        if not is_student(auth):
            raise Denied("Cần đăng nhập học sinh để nộp tệp.")
        asg = next((a for a in _all_asg() if a[0] == aid and a[1] == auth["cls"]), None)
        if not asg:
            raise Denied("Không tìm thấy bài giao của lớp em.")
        code, who = auth["cls"], auth["key"]
    else:
        raise Denied("Loại tệp không hợp lệ.")
    name = safe_name(name)
    if name.rsplit(".", 1)[-1].lower() not in ALLOWED_EXT or "." not in name:
        raise Denied("Chỉ nhận tệp: " + ", ".join(sorted(ALLOWED_EXT)) + ".")
    if not data:
        raise Denied("Tệp rỗng.")
    if len(data) > size_limit(name):
        raise Denied(f"Tệp quá lớn (tối đa {size_limit(name) // 1_000_000 if ext_of(name) in IMG_EXT else MAX_FILE // 1000} {'MB' if ext_of(name) in IMG_EXT else 'KB'}).")
    if ext_of(name) in IMG_EXT and len(data) > MAX_FILE // 2:
        name, data, mime = shrink_image(name, data)
    fid = secrets.token_hex(5)
    b64 = base64.b64encode(data).decode("ascii")
    chunks = [[fid, i, b64[o:o + CHUNK]] for i, o in enumerate(range(0, len(b64), CHUNK))]
    hs.tbl_append_many("filedata", DATA_H, chunks)
    hs.tbl_append("files", FILE_H, [fid, aid, code, who, kind, name, mime or "application/octet-stream", len(data), now])
    return fid


def _all_asg():
    return [_pad(r, 7) for r in hs.tbl_read("assignments", ASG_H)]


def list_files(auth, aid, kind=None, student=None, force=False):
    """Tệp của một bài giao mà người gọi được phép thấy (học sinh chỉ thấy đề của lớp và tệp nộp của mình)."""
    if not (is_teacher(auth) or is_student(auth)):
        raise Denied("Cần đăng nhập.")
    out = [_file_meta(r) for r in hs.tbl_read("files", FILE_H, force=force) if _pad(r)[1] == aid]
    out = [m for m in out if _can_see(auth, m) and (kind is None or m["kind"] == kind)
           and (student is None or hs.slug(m["student"]) == hs.slug(student))]
    return sorted(out, key=lambda m: m["ts"])


def read_file(auth, fid):
    """(meta, bytes) của tệp nếu được phép, ngược lại Denied/None."""
    meta = next((_file_meta(r) for r in hs.tbl_read("files", FILE_H, force=True) if _pad(r)[0] == fid), None)
    if not meta or not _can_see(auth, meta):
        raise Denied("Không có quyền tải tệp này.")
    parts = sorted(((int(r[1]), r[2]) for r in hs.tbl_read("filedata", DATA_H, force=True) if len(r) >= 3 and r[0] == fid))
    return meta, base64.b64decode("".join(p for _, p in parts))


def delete_file(auth, fid):
    meta = next((_file_meta(r) for r in hs.tbl_read("files", FILE_H, force=True) if _pad(r)[0] == fid), None)
    if not meta:
        return
    if not (is_teacher(auth) or (meta["kind"] == SUBF and is_student(auth) and hs.slug(meta["student"]) == hs.slug(auth["key"]) and meta["code"] == auth["cls"])):
        raise Denied("Không có quyền xóa tệp này.")
    _purge_files(lambda r: r[0] == fid)


def _purge_files(pred):
    """Xóa các tệp (và mảnh dữ liệu) có dòng metadata thỏa pred."""
    rows = hs.tbl_read("files", FILE_H, force=True)
    gone = {_pad(r)[0] for r in rows if pred(_pad(r))}
    if not gone:
        return
    hs.tbl_write("files", FILE_H, [r for r in rows if _pad(r)[0] not in gone])
    data = hs.tbl_read("filedata", DATA_H, force=True)
    hs.tbl_write("filedata", DATA_H, [r for r in data if (r + [""])[0] not in gone])


# ---------------- Phiếu trả lời (trắc nghiệm / đúng-sai / trả lời ngắn) ----------------
def docx_text(data):
    """Lấy chữ từ .docx (không cần thư viện ngoài), mỗi đoạn một dòng."""
    import zipfile
    from io import BytesIO
    try:
        xml = zipfile.ZipFile(BytesIO(data)).read("word/document.xml").decode("utf-8", "ignore")
    except Exception:
        return ""
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    import html as _h
    return _h.unescape(re.sub(r"<[^>]+>", "", xml)).strip()


def detect_structure(text):
    """Đoán số câu mỗi phần từ đề: {'mc': n, 'tf': n, 'sa': n} (0 nếu không thấy)."""
    parts = re.split(r"(?im)^\s*PHẦN\s+(I{1,3}|IV)\b", text)
    out = {"mc": 0, "tf": 0, "sa": 0}
    names = {"I": "mc", "II": "tf", "III": "sa"}
    for i in range(1, len(parts) - 1, 2):
        k = names.get(parts[i].upper())
        if k:
            nums = {int(n) for n in re.findall(r"(?m)^\s*Câu\s+(\d+)\s*[.:]", parts[i + 1])}
            out[k] = max(out[k], len(nums))
    return out


def _tf_bools(s):
    """'ĐSĐĐ' / 'DSDD' / 'TFTT' -> [True, False, ...]; ký tự lạ -> None."""
    out = []
    for ch in re.sub(r"[\s,;-]", "", (s or "").upper()):
        out.append(True if ch in "ĐDT1" else False if ch in "SF0" else None)
    return out


def clean_sheet(cfg):
    """Chuẩn hóa cấu hình phiếu từ giáo viên: mc = chuỗi chữ A-D (rỗng nếu chưa có), tf = chuỗi Đ/S, sa = đáp án."""
    mc = [(x or "").strip().upper()[:1] for x in cfg.get("mc", [])]
    mc = [x if x in "ABCD" and x else "" for x in mc]
    tf = ["".join("Đ" if b else "S" for b in _tf_bools(x) if b is not None) for x in cfg.get("tf", [])]
    sa = [(x or "").strip()[:60] for x in cfg.get("sa", [])]
    if len(mc) > 60 or len(tf) > 20 or len(sa) > 40:
        raise Denied("Phiếu có quá nhiều câu.")
    if not (mc or tf or sa):
        raise Denied("Phiếu cần có ít nhất một câu.")
    if any(len(x) > 8 for x in tf):
        raise Denied("Mỗi câu đúng/sai tối đa 8 ý.")
    return {"mc": mc, "tf": tf, "sa": sa, "n_tf_items": [len(x) or 4 for x in tf], "show_key": bool(cfg.get("show_key", True))}


def _num(x):
    try:
        return float(str(x).strip().replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def _sa_match(given, key):
    g = (given or "").strip()
    if not g or not key:
        return False
    for alt in key.split(";"):
        alt = alt.strip()
        a, b = _num(g), _num(alt)
        if a is not None and b is not None:
            if abs(a - b) <= 1e-9 + 1e-9 * abs(b):
                return True
        elif g.lower() == alt.lower():
            return True
    return False


def grade_sheet(cfg, ans):
    """Chấm phiếu. Câu chưa có đáp án -> None (không tính điểm). Điểm theo thang THPT (0,25/câu TN và TLN; đúng/sai 0,1-0,25-0,5-1)."""
    res = {"mc": [], "tf": [], "sa": []}
    score = mx = 0.0
    right = {"mc": 0, "tf": 0, "sa": 0}
    mca = (ans.get("mc") or []) + [""] * len(cfg["mc"])
    for i, key in enumerate(cfg["mc"]):
        if not key:
            res["mc"].append(None)
            continue
        ok = (mca[i] or "").upper() == key
        res["mc"].append(ok)
        mx += MC_POINT
        if ok:
            score += MC_POINT
            right["mc"] += 1
    tfa = (ans.get("tf") or []) + [[]] * len(cfg["tf"])
    for i, key in enumerate(cfg["tf"]):
        kb = _tf_bools(key)
        if not kb:
            res["tf"].append(None)
            continue
        given = list(tfa[i]) + [None] * len(kb)
        marks = [given[j] is not None and bool(given[j]) == kb[j] for j in range(len(kb))]
        res["tf"].append(marks)
        n_ok = sum(marks)
        mx += 1.0
        score += TF_POINTS[n_ok] if len(kb) == 4 else round(n_ok / len(kb), 2)
        right["tf"] += n_ok == len(kb)
    saa = (ans.get("sa") or []) + [""] * len(cfg["sa"])
    for i, key in enumerate(cfg["sa"]):
        if not key:
            res["sa"].append(None)
            continue
        ok = _sa_match(saa[i], key)
        res["sa"].append(ok)
        mx += SA_POINT
        if ok:
            score += SA_POINT
            right["sa"] += 1
    return {"detail": res, "score": round(score, 2), "max": round(mx, 2), "right": right}


def _find_asg(aid):
    return next((a for a in _all_asg() if a[0] == aid), None)


def set_sheet(auth, aid, cfg):
    _need_teacher(auth)
    asg = _find_asg(aid)
    if not asg:
        raise Denied("Không tìm thấy bài giao.")
    cfg = clean_sheet(cfg)
    rows = [r for r in hs.tbl_read("sheets", SHEET_H, force=True) if (r + [""])[0] != aid]
    rows.append([aid, asg[1], json.dumps(cfg, ensure_ascii=False)])
    hs.tbl_write("sheets", SHEET_H, rows)


def _sheet_row(aid, force=False):
    for r in hs.tbl_read("sheets", SHEET_H, force=force):
        if len(r) >= 3 and r[0] == aid:
            try:
                return r[1], json.loads(r[2])
            except ValueError:
                return None
    return None


def get_sheet(auth, aid, force=False):
    """Giáo viên: đủ đáp án. Học sinh: chỉ cấu trúc (số câu, số ý), tuyệt đối không có đáp án. Chưa có phiếu -> None."""
    got = _sheet_row(aid, force)
    if not got:
        return None
    code, cfg = got
    if is_teacher(auth):
        return cfg
    if not is_student(auth) or auth["cls"] != code:
        raise Denied("Không có quyền xem phiếu này.")
    return {"mc": ["?"] * len(cfg["mc"]), "tf": ["?" * n for n in cfg.get("n_tf_items", [4] * len(cfg["tf"]))],
            "sa": ["?"] * len(cfg["sa"])}


def sheet_review(auth, aid):
    """Đáp án đúng để học sinh xem lại: chỉ khi giáo viên cho phép và học sinh đã nộp ít nhất một lần."""
    got = _sheet_row(aid, True)
    if not got:
        return None
    code, cfg = got
    if is_teacher(auth):
        return cfg
    if not is_student(auth) or auth["cls"] != code or not cfg.get("show_key", True):
        return None
    if not sheet_results(auth, aid, force=True):
        return None
    return {"mc": cfg["mc"], "tf": cfg["tf"], "sa": cfg["sa"]}


def asg_minutes(aid):
    """Số phút làm bài của một bài giao (0 = không giới hạn)."""
    for r in hs.tbl_read("assignments", ASG_H):
        if r and r[0] == aid:
            return int(r[9]) if len(r) > 9 and str(r[9]).isdigit() else 0
    return 0


def get_start(auth, aid):
    """Thời điểm (giây epoch) học sinh bấm Bắt đầu làm bài này, hoặc None."""
    if not is_student(auth):
        return None
    for r in hs.tbl_read("starts", STARTS_H, force=True):
        if len(r) >= 4 and r[0] == aid and r[2] == auth["key"]:
            try:
                return float(r[3])
            except ValueError:
                return None
    return None


def begin_attempt(auth, aid, ts):
    """Ghi giờ bắt đầu (lưu ở máy chủ nên tải lại trang không làm lại đồng hồ). Đã bắt đầu thì giữ giờ cũ."""
    old = get_start(auth, aid)
    if old is not None:
        return old
    hs.tbl_append("starts", STARTS_H, [aid, auth["cls"], auth["key"], f"{ts:.0f}"])
    return ts


def clear_start(auth, aid):
    rows = hs.tbl_read("starts", STARTS_H, force=True)
    keep = [r for r in rows if not (len(r) >= 3 and r[0] == aid and r[2] == auth["key"])]
    if len(keep) != len(rows):
        hs.tbl_write("starts", STARTS_H, keep)


def missing_parts(cfg, ans):
    """Các ô chưa làm: {'mc': [số câu], 'tf': [(số câu, [ý])], 'sa': [số câu]} (số câu tính từ 1)."""
    mcs, sas = ans.get("mc") or [], ans.get("sa") or []
    mc = [i + 1 for i in range(len(cfg["mc"])) if i >= len(mcs) or not mcs[i]]
    tf = []
    for i, items in enumerate(cfg["tf"]):
        row = (ans.get("tf") or [])[i] if i < len(ans.get("tf") or []) else []
        miss = [j for j in range(len(items)) if j >= len(row) or row[j] is None]
        if miss:
            tf.append((i + 1, miss))
    sa = [i + 1 for i in range(len(cfg["sa"])) if i >= len(sas) or not str(sas[i]).strip()]
    return {"mc": mc, "tf": tf, "sa": sa}


def missing_text(parts, lang="vi"):
    vi = lang == "vi"
    out = []
    if parts["mc"]:
        out.append(("Phần I câu " if vi else "Part I Q") + ", ".join(map(str, parts["mc"])))
    if parts["tf"]:
        out.append(("Phần II " if vi else "Part II ") + "; ".join((f"câu {q} ý " if vi else f"Q{q} ") + ", ".join("abcdefgh"[j] for j in js) for q, js in parts["tf"]))
    if parts["sa"]:
        out.append(("Phần III câu " if vi else "Part III Q") + ", ".join(map(str, parts["sa"])))
    return " · ".join(out)


def submit_sheet(auth, aid, ans, now):
    """Học sinh nộp phiếu; chấm ở máy chủ rồi lưu. Phải làm đủ mọi ô mới được nộp (trừ khi đã hết giờ);
    bài có giới hạn thời gian phải bấm Bắt đầu trước và nộp trong hạn. Trả về kết quả chấm (không lộ đáp án đúng)."""
    if not is_student(auth):
        raise Denied("Cần đăng nhập học sinh để nộp phiếu.")
    got = _sheet_row(aid, True)
    if not got or got[0] != auth["cls"]:
        raise Denied("Không tìm thấy phiếu trả lời của lớp em.")
    cfg = got[1]
    clean = {"mc": [str(x or "")[:1].upper() for x in (ans.get("mc") or [])][:len(cfg["mc"])],
             "tf": [[(None if b is None else bool(b)) for b in row][:8] for row in (ans.get("tf") or [])][:len(cfg["tf"])],
             "sa": [str(x or "").strip()[:60] for x in (ans.get("sa") or [])][:len(cfg["sa"])]}
    mins, expired = asg_minutes(aid), False
    if mins:
        t0 = get_start(auth, aid)
        if t0 is None:
            raise Denied("Bài có giới hạn thời gian: hãy bấm \"Bắt đầu làm bài\" trước.")
        dl = t0 + mins * 60
        if time.time() > dl + GRACE:
            raise Denied("Đã hết giờ làm bài.")
        expired = time.time() >= dl - 3
    miss = missing_parts(cfg, clean)
    if (miss["mc"] or miss["tf"] or miss["sa"]) and not expired:
        raise Denied("Chưa làm đủ các ô, còn thiếu: " + missing_text(miss))
    g = grade_sheet(cfg, clean)
    hs.tbl_append("sheetsubs", SSUB_H, [aid, auth["cls"], auth["key"], now, json.dumps(clean, ensure_ascii=False), g["score"],
                                        json.dumps({"detail": g["detail"], "max": g["max"], "right": g["right"]}, ensure_ascii=False)])
    if mins:
        clear_start(auth, aid)
    return g


def sheet_results(auth, aid, student=None, force=False):
    """Các lần nộp phiếu của một bài. Giáo viên xem tất cả; học sinh chỉ xem của chính mình."""
    if is_student(auth):
        student = auth["key"]
    elif not is_teacher(auth):
        raise Denied("Cần đăng nhập.")
    out = []
    for r in hs.tbl_read("sheetsubs", SSUB_H, force=force):
        r = r + [""] * (7 - len(r))
        if r[0] != aid or (student and hs.slug(r[2]) != hs.slug(student)):
            continue
        try:
            d, a = json.loads(r[6]), json.loads(r[4])
        except ValueError:
            d, a = {}, {}
        try:
            sc = float(r[5])
        except ValueError:
            sc = 0.0
        out.append({"student": r[2], "ts": r[3], "score": sc, "max": d.get("max", 0), "detail": d.get("detail", {}),
                    "right": d.get("right", {}), "answers": a})
    return out



# ---------------- Đọc đáp án có sẵn trong file Word ----------------
KEY_MARK = re.compile(r"^\s*(?:BẢNG\s+)?(?:ĐÁP\s*ÁN|HƯỚNG\s*DẪN\s*(?:CHẤM|GIẢI)|LỜI\s*GIẢI)", re.I)
_ALPHA = "A-Za-zÀ-ỹ0-9"


def _unesc(t):
    import html as _h
    return _h.unescape(t)


def _body_spans(xml):
    """Các phần tử cấp cao của thân tài liệu: [(loại, bắt đầu, kết thúc)] với loại p / tbl / sdt."""
    b = xml.find("<w:body")
    if b < 0:
        return []
    b = xml.find(">", b) + 1
    spans, depth, start, insect, sstart = [], 0, 0, False, 0
    for m in re.finditer(r"<(/?)(w:p|w:tbl|w:sdt|w:sectPr)(?=[\s>/])[^>]*?(/?)>", xml[b:]):
        close, tag, selfc = m.group(1), m.group(2), m.group(3)
        a, e = b + m.start(), b + m.end()
        if tag == "w:sectPr":
            if depth == 0:
                if close:
                    insect = False
                    spans.append(("sect", sstart, e))
                elif selfc:
                    spans.append(("sect", a, e))
                else:
                    insect, sstart = True, a
            continue
        if insect:
            continue
        if close:
            depth -= 1
            if depth == 0:
                spans.append((tag[2:], start, e))
        elif selfc:
            if depth == 0:
                spans.append((tag[2:], a, e))
        else:
            if depth == 0:
                start = a
            depth += 1
    return spans


def _runs(pxml):
    """[(chữ, cờ định dạng)] của một đoạn; cờ gồm đậm, gạch chân, màu khác đen, tô sáng."""
    out = []
    for r in re.finditer(r"<w:r(?:\s[^>]*)?>(.*?)</w:r>", pxml, re.S):
        rx = r.group(1)
        t = "".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", rx))
        t = _unesc(t) + ("\t" if "<w:tab/>" in rx else "")
        if not t:
            continue
        rp = re.search(r"<w:rPr>(.*?)</w:rPr>", rx, re.S)
        rp = rp.group(1) if rp else ""
        fl = set()
        if re.search(r'<w:b(?:\s[^>]*)?/>', rp) and not re.search(r'<w:b\s+w:val="(?:0|false)"', rp):
            fl.add("b")
        if re.search(r'<w:u\s+w:val="(?!none)', rp):
            fl.add("u")
        if re.search(r'<w:color\s+w:val="(?!auto|000000|FFFFFF)', rp, re.I):
            fl.add("c")
        if "<w:highlight" in rp or re.search(r'<w:shd\s[^>]*w:fill="(?!auto|FFFFFF)', rp, re.I):
            fl.add("h")
        out.append((t, fl))
    return out


def docx_elements(data):
    """Thân Word thành danh sách: ('p', chữ, runs) hoặc ('t', hàng-ô). Kèm danh sách span để cắt file."""
    import zipfile
    from io import BytesIO
    try:
        xml = zipfile.ZipFile(BytesIO(data)).read("word/document.xml").decode("utf-8", "ignore")
    except Exception:
        return [], [], ""
    spans = _body_spans(xml)
    els = []
    for kind, a, b in spans:
        sx = xml[a:b]
        if kind == "p":
            rs = _runs(sx)
            els.append(("p", "".join(t for t, _ in rs).strip(), rs))
        elif kind == "tbl":
            rows = []
            for tr in re.findall(r"<w:tr(?:\s[^>]*)?>(.*?)</w:tr>", sx, re.S):
                cells = []
                for tc in re.findall(r"<w:tc>(.*?)</w:tc>", tr, re.S):
                    cells.append(" ".join("".join(t for t, _ in _runs(px)).strip() for px in re.findall(r"<w:p[ >].*?</w:p>", tc, re.S)).strip())
                rows.append(cells)
            els.append(("t", rows, []))
        else:
            els.append(("x", "", []))
    return els, spans, xml


def _key_marker(els):
    """Chỉ số phần tử mở đầu phần đáp án (tiêu đề ngắn, không phải dòng 'Đáp án: B' dưới từng câu)."""
    seen_q = 0
    for i, e in enumerate(els):
        if e[0] != "p":
            continue
        t = e[1]
        if re.match(r"Câu\s+\d+\s*[.:]", t):
            seen_q += 1
        if KEY_MARK.match(t) and len(t) <= 100 and not re.search(r"[:：]\s*(?:[A-D]\b|[-\d])", t):
            nxt = [x for x in els[i + 1:i + 4] if x[0] in ("p", "t")]
            if seen_q >= 1 or nxt:
                return i
    return None


def _norm_tf_val(v):
    return v.upper() in ("Đ", "ĐÚNG", "T", "D")


_TF_COMPACT = re.compile(r"[ĐS](?:[\s,;\-–]*[ĐS]){1,7}")


def _parse_table_groups(rows):
    """Bảng đáp án dạng cột: tiêu đề có 'Câu', mỗi nhóm cột = số câu + (lệnh hỏi) + đáp án; hỗ trợ ô gộp dọc và nhiều nhóm cạnh nhau."""
    mc, tf, sa, tfd = {}, {}, {}, {}
    hi = next((i for i, r in enumerate(rows) if any(re.fullmatch(r"(?:số\s+)?câu(?:\s+hỏi)?", c.strip(), re.I) for c in r)), None)
    if hi is None:
        return mc, tf, sa
    cols = [j for j, c in enumerate(rows[hi]) if re.fullmatch(r"(?:số\s+)?câu(?:\s+hỏi)?", c.strip(), re.I)]
    last = [None] * len(cols)
    for r in rows[hi + 1:]:
        for gi, c in enumerate(cols):
            end = cols[gi + 1] if gi + 1 < len(cols) else len(r)
            cell = r[c].strip() if c < len(r) else ""
            if re.fullmatch(r"(?:Câu\s*)?\d{1,2}", cell, re.I):
                last[gi] = int(re.sub(r"\D", "", cell))
            elif cell:
                continue
            num = last[gi]
            fields = [r[j].strip() for j in range(c + 1, min(end, len(r))) if r[j].strip()]
            if num is None or not fields:
                continue
            item = None
            multi = next((re.findall(r"([a-d])\s*[).:\-–]?\s*(Đúng|Sai|Đ|S)(?![A-Za-zÀ-ỹ])", f) for f in fields
                          if len(re.findall(r"([a-d])\s*[).:\-–]?\s*(Đúng|Sai|Đ|S)(?![A-Za-zÀ-ỹ])", f)) >= 2), None)
            if multi:                                              # một ô chứa cả bốn ý: "a) Đ b) S c) Đ d) S"
                tf[num] = "".join("Đ" if _norm_tf_val(v) else "S" for _, v in multi)
                continue
            for k, f in enumerate(fields):
                mm = re.fullmatch(r"([a-d])\s*[).:\-–]?\s*(Đúng|Sai|Đ|S)", f, re.I)
                if mm:
                    item = (mm.group(1).lower(), mm.group(2))
                    break
                if re.fullmatch(r"([a-d])\s*[).:]?", f) and k + 1 < len(fields) and re.fullmatch(r"(Đúng|Sai|Đ|S)", fields[k + 1], re.I):
                    item = (f[0], fields[k + 1])
                    break
            if item:
                tfd.setdefault(num, {})[item[0]] = _norm_tf_val(item[1])
            elif any(_TF_COMPACT.fullmatch(f) for f in fields):
                tf[num] = re.sub(r"[^ĐS]", "", next(f for f in fields if _TF_COMPACT.fullmatch(f)))
            elif any(re.fullmatch(r"[A-D]", f) for f in fields):
                mc[num] = next(f for f in fields if re.fullmatch(r"[A-D]", f))
            else:
                sa[num] = fields[-1][:40]
    for n, d in tfd.items():
        if len(d) >= 2:
            tf[n] = "".join("Đ" if d[L] else "S" for L in sorted(d))
    return mc, tf, sa


def _parse_key_region(region, struct_hint=None):
    """Đọc đáp án từ phần đáp án (bảng và dòng chữ)."""
    mc, tf, sa = {}, {}, {}
    lines = []
    for e in region:
        if e[0] == "t":
            rows = [[c.strip() for c in r] for r in e[1] if any(c.strip() for c in r)]
            used = False
            for a, b in zip(rows, rows[1:]):                      # hàng số câu + hàng đáp án (bảng ngang)
                na = [c for c in a[1:] if c]
                nb = [c for c in b[1:] if c]
                if len(na) >= 2 and len(na) == len(nb) and all(re.fullmatch(r"\d{1,2}", re.sub(r"\D", "", c) or "x") and re.search(r"\d", c) for c in na):
                    nums = [int(re.sub(r"\D", "", x)) for x in na]
                    if all(re.fullmatch(r"[A-D]", c.strip().upper()) for c in nb):
                        mc.update({n: y.strip().upper() for n, y in zip(nums, nb)})
                        used = True
                    elif all(_TF_COMPACT.fullmatch(c.strip()) for c in nb):
                        tf.update({n: re.sub(r"[^ĐS]", "", y) for n, y in zip(nums, nb)})
                        used = True
                    elif len(na) >= 3 and all(re.fullmatch(r"-?\d[\d.,]*\s*\S{0,6}", c.strip()) for c in nb) and not all(re.fullmatch(r"\d{1,2}", c) for c in nb):
                        sa.update({n: y.strip()[:40] for n, y in zip(nums, nb)})
                        used = True
            if not used:
                g_mc, g_tf, g_sa = _parse_table_groups(rows)
                if g_mc or g_tf or g_sa:
                    mc.update(g_mc)
                    tf.update(g_tf)
                    sa.update(g_sa)
                    used = True
            for r in rows:                                         # (Câu, Đáp án) lặp theo hàng
                for k in range(len(r) - 1):
                    if re.fullmatch(r"(?:Câu\s*)?\d{1,2}", r[k], re.I) and re.fullmatch(r"[A-D]", r[k + 1].upper()):
                        mc[int(re.sub(r"\D", "", r[k]))] = r[k + 1].upper()
                        used = True
            if not used:
                for r in rows:
                    lines.append(" ".join(r))
        elif e[0] == "p" and e[1]:
            lines.append(e[1])
    cur = None
    tfd = {}
    keep, skip = [], False                                     # hai dòng liền nhau: hàng số câu rồi hàng đáp án
    for i, ln in enumerate(lines):
        if skip:
            skip = False
            continue
        a = re.fullmatch(r"(?:Câu\s*)?((?:\d{1,2}\s*){3,})", ln.strip(), re.I)
        b = re.fullmatch(r"(?:Đáp\s*án\s*)?((?:[A-D]\s*){3,})", lines[i + 1].strip(), re.I) if i + 1 < len(lines) else None
        if a and b and len(a.group(1).split()) == len(b.group(1).split()):
            for n, L in zip(a.group(1).split(), b.group(1).split()):
                mc[int(n)] = L.upper()
            skip = True
            continue
        keep.append(ln)
    for ln in keep:
        ln = re.sub(r"\s*\|\s*", " ", ln).strip()
        ln = re.sub(r"(?i)^PHẦN\s+I{1,3}\s*[:.\-–]?\s*", "", ln)
        if not ln:
            continue
        toks = re.findall(r"(?<![%s])([a-d])\s*[).:\-–]?\s*(Đúng|Sai|Đ|S|T|F)(?![%s])" % (_ALPHA, _ALPHA), ln)
        mq = re.match(r"(?:Câu\s*)?(\d{1,2})\b", ln, re.I)
        if toks:
            n = int(mq.group(1)) if mq and not re.match(r"[a-d]\b", ln) else cur
            if n is not None:
                for L, v in toks:
                    tfd.setdefault(n, {})[L] = _norm_tf_val(v)
                cur = n
            continue
        comp = re.match(r"(?:Câu\s*)?(\d{1,2})\s*[:.\-–]?\s*([ĐS](?:[\s,;\-–]*[ĐS]){1,7})\s*$", ln)
        if comp:
            tf[int(comp.group(1))] = re.sub(r"[^ĐS]", "", comp.group(2))
            continue
        pairs = re.findall(r"(?:Câu\s*)?(\d{1,2})\s*[.:\-–)]*\s*([ABCD])(?![%s])" % _ALPHA, ln)
        if pairs:
            for n, L in pairs:
                mc.setdefault(int(n), L)
            continue
        if mq:
            cur = int(mq.group(1))
        m2 = re.match(r"(?:Câu\s*)?(\d{1,2})\s*[:.\-–]?\s*(-?\d[\d.,]*\s*[^\s\d]{0,8})\s*$", ln, re.I)
        if m2:
            sa[int(m2.group(1))] = m2.group(2).strip()
    for n, d in tfd.items():
        if all(L in d for L in "abcd"[:max(2, len(d))]) and len(d) >= 2:
            tf[n] = "".join("Đ" if d[L] else "S" for L in sorted(d))
    return mc, tf, sa


def _parse_inline(els):
    """Đáp án nằm ngay dưới từng câu: 'Đáp án: B', '(Đúng)' sau ý, ..."""
    mc, tf, sa, part, n = {}, {}, {}, None, None
    tfd = {}
    for e in els:
        if e[0] != "p" or not e[1]:
            continue
        t = e[1]
        mp = re.match(r"(?i)PHẦN\s+(I{1,3})\b", t)
        if mp:
            part = {"I": "mc", "II": "tf", "III": "sa"}.get(mp.group(1).upper())
            continue
        mq = re.match(r"Câu\s+(\d+)\s*[.:]", t)
        if mq:
            n = int(mq.group(1))
        ma = re.match(r"(?i)\s*(?:Đáp\s*án|ĐA|Chọn(?:\s+đáp\s+án)?)\s*(?:đúng)?\s*[:：.]?\s*(\S.*)$", t)
        if ma and n is not None:
            v = ma.group(1).strip()
            if part in (None, "mc") and re.fullmatch(r"[ABCD]\b.*", v) and len(v) <= 3:
                mc[n] = v[0]
            elif part == "sa":
                sa[n] = v[:40]
            continue
        mi = re.match(r"([a-d])\s*[).]", t)
        if mi and part in (None, "tf") and n is not None:
            mv = re.search(r"[(\[:→\-–]\s*(Đúng|Sai)\s*[)\]]?\s*\.?$", t)
            if mv:
                tfd.setdefault(n, {})[mi.group(1)] = mv.group(1) == "Đúng"
    for k, d in tfd.items():
        if len(d) >= 2:
            tf[k] = "".join("Đ" if d[L] else "S" for L in sorted(d))
    return mc, tf, sa


def _parse_format(els):
    """Đáp án trắc nghiệm được đánh dấu bằng gạch chân / màu / tô sáng ở chữ A–D (đúng một đáp án mỗi câu)."""
    mc, part, n = {}, None, None
    flagged = {}
    for e in els:
        if e[0] != "p" or not e[1]:
            continue
        t = e[1]
        mp = re.match(r"(?i)PHẦN\s+(I{1,3})\b", t)
        if mp:
            part = mp.group(1).upper()
            continue
        mq = re.match(r"Câu\s+(\d+)\s*[.:]", t)
        if mq:
            n = int(mq.group(1))
        if part not in (None, "I") or n is None:
            continue
        pos = 0
        for txt, fl in e[2]:
            for m in re.finditer(r"(?<![%s])([A-D])\s*[.)]" % _ALPHA, txt):
                f = bool(fl & {"u", "c", "h"})
                flagged.setdefault(n, {})
                flagged[n][m.group(1)] = flagged[n].get(m.group(1), False) or f
    for k, d in flagged.items():
        hot = [L for L, f in d.items() if f]
        if len(d) >= 3 and len(hot) == 1:
            mc[k] = hot[0]
    return mc


def extract_key_els(els):
    """Tìm đáp án trong danh sách phần tử (Word hoặc văn bản từ PDF)."""
    km = _key_marker(els)
    has_q = any(e[0] == "p" and re.match(r"Câu\s+\d+\s*[.:]", e[1]) for e in els)
    res = {"mc": {}, "tf": {}, "sa": {}, "marker": km, "src": []}
    layers = []
    if km is not None:
        layers.append(("bảng/danh sách đáp án cuối đề", _parse_key_region(els[km + 1:])))
    elif not has_q:                                          # file chỉ có đáp án, không có tiêu đề
        layers.append(("file đáp án", _parse_key_region(els)))
    layers.append(("dòng đáp án dưới từng câu", _parse_inline(els[:km] if km is not None else els)))
    layers.append(("đáp án đánh dấu trong đề", (_parse_format(els[:km] if km is not None else els), {}, {})))
    for name, (mc, tf, sa) in layers:
        got = False
        for k, d in (("mc", mc), ("tf", tf), ("sa", sa)):
            for n, v in d.items():
                if n not in res[k]:
                    res[k][n] = v
                    got = True
        if got:
            res["src"].append(name)
    return res


def extract_key(data):
    """Tìm đáp án trong file Word. Trả về {'mc':{n:'B'}, 'tf':{n:'ĐSĐS'}, 'sa':{n:'12,5'}, 'marker': chỉ số|None, 'src': [...]}."""
    els, _, _ = docx_elements(data)
    return extract_key_els(els)


def text_elements(text):
    return [("p", ln.strip(), []) for ln in text.splitlines() if ln.strip()]


def pdf_text(data):
    """Chữ trong PDF (PDF có lớp chữ; ảnh quét không đọc được). Cần thư viện pypdf."""
    from io import BytesIO
    try:
        from pypdf import PdfReader
    except ImportError:
        raise Denied("Máy chủ chưa cài pypdf nên chưa đọc được PDF (thêm pypdf vào requirements.txt).")
    try:
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(BytesIO(data)).pages)
    except Exception:
        raise Denied("Không đọc được file PDF này.")


def analyze_key_file(name, data):
    """Đọc đáp án từ file .docx / .pdf / .txt: {'struct', 'key', 'src'}."""
    ext = ext_of(name)
    if ext == "docx":
        a = analyze_docx(data)
        return {"struct": a["struct"], "key": a["key"], "src": a["src"]}
    if ext == "pdf":
        text = pdf_text(data)
    elif ext == "txt":
        text = data.decode("utf-8", "ignore")
    else:
        raise Denied("Chỉ đọc file .docx, .pdf hoặc .txt.")
    els = text_elements(text)
    r = extract_key_els(els)
    if not r["mc"]:                                            # PDF làm phẳng bảng: mỗi ô một dòng
        flat = " ".join(e[1] for e in els) + " "
        km = _key_marker(els)
        if km is not None:
            flat = " ".join(e[1] for e in els[km + 1:]) + " "
        m = re.search(r"Câu\s+((?:\d{1,2}\s+){3,})Đáp\s*án\s+((?:[A-D]\s+){3,})", flat)
        if m:
            ns, ls = m.group(1).split(), m.group(2).split()
            if len(ns) == len(ls):
                r["mc"] = {int(n): L for n, L in zip(ns, ls)}
                r["src"].append("bảng đáp án trong PDF")
        if not r["mc"]:
            pairs = re.findall(r"(?<![%s])(\d{1,2})\s*[.:\-–)]?\s+([ABCD])(?![%s])" % (_ALPHA, _ALPHA), flat)
            if len(pairs) >= 3:
                r["mc"] = {int(n): L for n, L in pairs}
                r["src"].append("danh sách đáp án trong PDF")
    return {"struct": detect_structure(text), "key": {k: r[k] for k in ("mc", "tf", "sa")}, "src": r["src"]}


def key_only(data):
    """File chỉ có đáp án (không có câu hỏi trước phần đáp án)."""
    els, _, _ = docx_elements(data)
    km = _key_marker(els)
    if km is None:
        return False
    return not any(e[0] == "p" and re.match(r"Câu\s+\d+\s*[.:]", e[1]) for e in els[:km])


def strip_key_docx(data):
    """Bản dành cho học sinh: cắt từ tiêu đề phần đáp án đến hết tài liệu. None nếu không cắt được."""
    import zipfile
    from io import BytesIO
    els, spans, xml = docx_elements(data)
    km = _key_marker(els)
    if km is None or km >= len(spans) or spans[km][0] != "p":
        return None
    cut = spans[km][1]
    tail = next((a for kind, a, b in spans[km:] if kind == "sect"), None)
    end = tail if tail is not None else xml.find("</w:body>")
    if end < 0:
        return None
    new = xml[:cut] + xml[end:]
    zin = zipfile.ZipFile(BytesIO(data))
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for it in zin.infolist():
            zo.writestr(it, new.encode("utf-8") if it.filename == "word/document.xml" else zin.read(it.filename))
    return out.getvalue()


def cfg_from_key(key, struct):
    """Ghép đáp án đọc được với số câu của đề thành cấu hình phiếu. Số câu nối tiếp (19-22, 23-28) được dịch về 1…; đáp án vượt số câu của đề bị bỏ."""
    def shift(d):
        if d and 1 not in d:
            off = min(d) - 1
            return {n - off: v for n, v in d.items()}
        return d
    mc, tf, sa = dict(key["mc"]), shift(dict(key["tf"])), shift(dict(key["sa"]))
    out = {}
    for k, d in (("mc", mc), ("tf", tf), ("sa", sa)):
        n = struct.get(k, 0)
        if n:
            d = {i: v for i, v in d.items() if i <= n}
        else:
            n = max(d, default=0)
        out[k] = [d.get(i, "") for i in range(1, n + 1)]
    return out


def key_debug(name, data, limit=70):
    """Văn bản cho giáo viên xem app đã nhìn thấy gì trong phần đáp án của file (để đối chiếu khi đọc sai)."""
    ext = ext_of(name)
    if ext == "docx":
        els, _, _ = docx_elements(data)
        km = _key_marker(els)
        has_q = any(e[0] == "p" and re.match(r"Câu\s+\d+\s*[.:]", e[1]) for e in els)
        region = els[km + 1:] if km is not None else (els if not has_q else [])
        lines = []
        for e in region:
            if e[0] == "t":
                lines += [" | ".join(r) for r in e[1] if any(c.strip() for c in r)]
            elif e[1]:
                lines.append(e[1])
    else:
        try:
            text = pdf_text(data) if ext == "pdf" else data.decode("utf-8", "ignore")
        except Denied:
            text = ""
        lines = [x for x in text.splitlines() if x.strip()]
        els = text_elements(text)
        km = _key_marker(els)
        if km is not None:
            lines = [e[1] for e in els[km + 1:]]
    if not lines:
        return "(Không thấy phần đáp án trong file: không có tiêu đề ĐÁP ÁN / HƯỚNG DẪN CHẤM.)"
    return "\n".join(lines[:limit]) + ("\n…" if len(lines) > limit else "")


def analyze_docx(data):
    """Phân tích một file Word đề: số câu từng phần, đáp án có sẵn, file chỉ-đáp-án, bản học sinh đã cắt đáp án."""
    key = extract_key(data)
    return {"struct": detect_structure(docx_text(data)), "key": {k: key[k] for k in ("mc", "tf", "sa")}, "src": key["src"],
            "key_only": key_only(data), "has_marker": key["marker"] is not None,
            "stripped": strip_key_docx(data) if key["marker"] is not None else None}


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
