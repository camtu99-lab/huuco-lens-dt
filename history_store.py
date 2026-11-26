"""Lưu lịch sử tra cứu của từng học sinh.

Hai nơi lưu, cùng một bộ hàm:
  * Google Sheets (bền, giáo viên mở bảng tính xem trực tiếp): bật bằng configure_sheets(...), app.py gọi khi
    secrets có HISTORY_SHEET_ID và [gcp_service_account].
  * Tệp JSON trong data/history/ (mặc định khi chưa cấu hình). Trên Streamlit Cloud tệp mất khi app khởi động lại.

Mỗi lượt: {"q": nội dung, "k": loại, "d": ngày, "t": giờ, "p": dữ liệu tra lại (tùy chọn)}, mới nhất đứng đầu.
Không dùng streamlit để dễ kiểm thử. Lỗi mạng/Sheets được đổi thành OSError để app bắt chung với lỗi ổ đĩa.
"""
import csv
import io
import json
import os
import re
import tempfile
import threading
import time
import unicodedata

BASE = os.environ.get("HISTORY_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "history")
MAX_KEEP = 300          # số lượt tối đa giữ cho mỗi học sinh (chỉ áp dụng cho tệp cục bộ)
_LOCK = threading.RLock()

last_error = ""          # lỗi gần nhất của Google Sheets (hiện ở tab giáo viên)


def slug(name):
    """Tên không dấu, chữ thường, chỉ gồm a-z 0-9 và _ (rỗng nếu không có tên)."""
    s = unicodedata.normalize("NFD", (name or "").lower().replace("đ", "d"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:40]


# =====================================================================
# Nơi lưu 1: Google Sheets
# =====================================================================
_CFG = None              # (sheet_id, thông tin service account)
_BOOK = None             # bảng tính đang mở
_TBL = {}                # tên bảng chung -> {"ws":..., "rows":..., "t":...}
_WS = None               # (bảng "lookups", bảng "visits")
_CACHE = {"t": 0.0, "look": None, "vis": None}
_TTL = 20                # giây giữ bản đọc trong bộ nhớ để không gọi API mỗi lần chạy lại trang
LOOK_HEAD = ["hoc_sinh", "ngay", "gio", "loai", "noi_dung", "du_lieu_tra_lai"]
VIS_HEAD = ["hoc_sinh", "thoi_diem"]


def configure_sheets(sheet_id, creds):
    """Chỉ ghi nhớ cấu hình, chưa kết nối mạng (kết nối khi dùng lần đầu)."""
    global _CFG, _WS, _BOOK
    m = re.search(r"/d/([A-Za-z0-9_-]+)", str(sheet_id))      # cho phép dán cả đường dẫn, chỉ lấy phần ID
    cfg = (m.group(1) if m else str(sheet_id).strip().strip("\"'"), dict(creds))
    if _CFG != cfg:
        _CFG, _WS, _BOOK = cfg, None, None
        _TBL.clear()
        _CACHE.update(t=0.0, look=None, vis=None)


def backend_name():
    return "Google Sheets" if _CFG else "local"


def _book():
    """Mở bảng tính Google (một lần). Tách riêng để kiểm thử thay thế được."""
    global _BOOK
    if _BOOK is None:
        import gspread
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_info(
            _CFG[1], scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        _BOOK = gspread.authorize(creds).open_by_key(_CFG[0])
    return _BOOK


def _get_ws(title, head):
    sh = _book()
    try:
        return sh.worksheet(title)
    except Exception as e:
        if type(e).__name__ != "WorksheetNotFound":
            raise
        ws = sh.add_worksheet(title=title, rows=1000, cols=max(len(head), 6))
        ws.append_row(head)
        return ws


def _connect():
    """Hai trang tính lịch sử (lookups, visits); tạo nếu chưa có."""
    return _get_ws("lookups", LOOK_HEAD), _get_ws("visits", VIS_HEAD)


def _explain(e):
    """Câu báo lỗi dễ hiểu kèm cách khắc phục cho các lỗi hay gặp khi nối Google Sheets."""
    name, mail = type(e).__name__, (_CFG[1].get("client_email", "?") if _CFG else "?")
    if name == "SpreadsheetNotFound":
        return (f'SpreadsheetNotFound (404): không mở được bảng tính ID "{_CFG[0] if _CFG else "?"}". Kiểm tra: (1) đã bấm Chia sẻ bảng tính '
                f'cho {mail} với quyền Người chỉnh sửa chưa; (2) ID đúng là đoạn giữa /d/ và /edit trong địa chỉ; '
                f'(3) đây phải là Google Sheets thật (không phải file .xlsx tải lên Drive).')
    if name == "APIError" and "has not been used" in str(e):
        return "Chưa bật Google Sheets API hoặc Google Drive API trong dự án Google Cloud (bước 2 của hướng dẫn)."
    if name == "APIError" and "403" in str(e):
        return f"403: {mail} chưa có quyền chỉnh sửa bảng tính, hoặc chưa bật Sheets/Drive API."
    return f"{name}: {str(e)[:200]}"


def _sheets():
    global _WS, last_error
    try:
        if _WS is None:
            _WS = _connect()
        return _WS
    except Exception as e:      # mạng, quyền chưa chia sẻ, sai khóa...
        _WS = None
        last_error = _explain(e)
        raise OSError(last_error)


def _s_rows(force=False):
    """(các dòng lookups, các dòng visits) không gồm dòng tiêu đề, đọc kèm bộ nhớ đệm ngắn hạn."""
    global last_error
    with _LOCK:
        if not force and _CACHE["look"] is not None and time.time() - _CACHE["t"] < _TTL:
            return _CACHE["look"], _CACHE["vis"]
        wl, wv = _sheets()
        try:
            look = wl.get_all_values()[1:]
            vis = wv.get_all_values()[1:]
        except Exception as e:
            last_error = _explain(e)
            raise OSError(last_error)
        _CACHE.update(t=time.time(), look=look, vis=vis)
        last_error = ""
        return look, vis


def _s_call(fn):
    global last_error
    try:
        return fn()
    except OSError:
        raise
    except Exception as e:
        last_error = _explain(e)
        raise OSError(last_error)


def _row_item(r):
    r = list(r) + [""] * (6 - len(r))
    e = {"q": r[4], "k": r[3], "d": r[1], "t": r[2]}
    if r[5]:
        try:
            e["p"] = json.loads(r[5])
        except ValueError:
            pass
    return e


def _item_row(name, e):
    return [name.strip(), e.get("d", ""), e.get("t", ""), e.get("k", ""), e.get("q", ""),
            json.dumps(e["p"], ensure_ascii=False) if e.get("p") else ""]


def _s_rewrite(look=None, vis=None):
    """Ghi lại toàn bộ một trang tính (dùng khi xóa/gộp, hiếm khi xảy ra)."""
    wl, wv = _sheets()
    for ws, head, rows in ((wl, LOOK_HEAD, look), (wv, VIS_HEAD, vis)):
        if rows is not None:
            ws.clear()
            ws.update(values=[head] + rows, range_name="A1")
    _CACHE.update(t=0.0, look=None, vis=None)


# =====================================================================
# Nơi lưu 2: tệp JSON cục bộ
# =====================================================================
def _path(name):
    sl = slug(name)
    return os.path.join(BASE, sl + ".json") if sl else None


def _read(p):
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("items"), list) else None
    except (OSError, ValueError):
        return None


def _write(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# =====================================================================
# Bộ hàm dùng chung (app.py chỉ gọi các hàm này)
# =====================================================================
def load(name):
    """Các lượt của học sinh (mới nhất trước). Rỗng nếu chưa có hoặc không có tên."""
    sl = slug(name)
    if not sl:
        return []
    if _CFG:
        look, _ = _s_rows()
        return [_row_item(r) for r in reversed(look) if r and slug(r[0]) == sl]
    p = _path(name)
    with _LOCK:
        d = _read(p)
    return d["items"] if d else []


def save(name, items):
    """Thay toàn bộ lượt của học sinh bằng `items` (mới nhất trước)."""
    sl = slug(name)
    if not sl:
        return False
    if _CFG:
        with _LOCK:
            look, _ = _s_rows(True)
            keep = [r for r in look if not (r and slug(r[0]) == sl)]
            _s_call(lambda: _s_rewrite(look=keep + [_item_row(name, e) for e in reversed(items)]))
        return True
    p = _path(name)
    with _LOCK:
        old = _read(p) or {}
        old.update({"name": name.strip(), "items": items[:MAX_KEEP]})
        _write(p, old)
    return True


def append(name, entry):
    """Thêm một lượt; bỏ qua nếu trùng hệt lượt liền trước. Trả về True nếu đã ghi."""
    sl = slug(name)
    if not sl:
        return False
    if _CFG:
        with _LOCK:
            look, _ = _s_rows()
            for r in reversed(look):
                if r and slug(r[0]) == sl:
                    if _row_item(r)["q"] == entry.get("q") and _row_item(r)["k"] == entry.get("k"):
                        return False
                    break
            row = _item_row(name, entry)
            _s_call(lambda: _sheets()[0].append_row(row, value_input_option="RAW"))
            look.append(row)   # cập nhật bộ nhớ đệm ngay, không phải đọc lại
        return True
    p = _path(name)
    with _LOCK:
        d = _read(p) or {"name": name.strip(), "items": []}
        items = d["items"]
        if items and items[0].get("q") == entry.get("q") and items[0].get("k") == entry.get("k"):
            return False
        items.insert(0, entry)
        del items[MAX_KEEP:]
        d["name"] = name.strip()
        d["last"] = f'{entry.get("d", "")} {entry.get("t", "")}'.strip()
        _write(p, d)
    return True


def clear(name, kinds=None):
    """Xóa toàn bộ lịch sử, hoặc chỉ các lượt thuộc những loại trong `kinds`."""
    sl = slug(name)
    if not sl:
        return
    ks = set(kinds) if kinds is not None else None
    if _CFG:
        with _LOCK:
            look, _ = _s_rows(True)
            keep = [r for r in look if not (r and slug(r[0]) == sl and (ks is None or (r + [""] * 4)[3] in ks))]
            _s_call(lambda: _s_rewrite(look=keep))
        return
    with _LOCK:
        d = _read(_path(name))
        if d:
            d["items"] = [] if ks is None else [h for h in d["items"] if h.get("k") not in ks]
            _write(_path(name), d)


def touch(name, ts):
    """Ghi một lần truy cập (lúc học sinh nhập tên). ts dạng 'YYYY-MM-DD HH:MM'."""
    sl = slug(name)
    if not sl:
        return
    if _CFG:
        with _LOCK:
            _, vis = _s_rows()
            _s_call(lambda: _sheets()[1].append_row([name.strip(), ts], value_input_option="RAW"))
            vis.append([name.strip(), ts])
        return
    p = _path(name)
    with _LOCK:
        d = _read(p) or {"name": name.strip(), "items": []}
        d["name"] = name.strip()
        d.setdefault("first", ts)
        d["last"] = ts
        v = d.setdefault("visits", [])
        if not v or v[0] != ts:
            v.insert(0, ts)
        del v[200:]
        _write(p, d)


def summary(force=False):
    """Mỗi học sinh một dòng: slug, name, first, last, visits, visit_log, total, by_kind. Mới truy cập nhất trước."""
    people = {}   # slug -> dict

    def get(sl, name):
        return people.setdefault(sl, {"slug": sl, "name": name or sl, "first": "", "last": "", "visit_log": [], "total": 0, "by_kind": {}})

    def stamp(x, ts):
        if ts and (not x["first"] or ts < x["first"]):
            x["first"] = ts
        if ts and ts > x["last"]:
            x["last"] = ts

    if _CFG:
        look, vis = _s_rows(force)
        for r in look:
            if r and slug(r[0]):
                it = _row_item(r)
                x = get(slug(r[0]), r[0])
                x["total"] += 1
                x["by_kind"][it["k"]] = x["by_kind"].get(it["k"], 0) + 1
                stamp(x, f'{it["d"]} {it["t"]}'.strip())
        for r in vis:
            if len(r) >= 2 and slug(r[0]):
                x = get(slug(r[0]), r[0])
                x["visit_log"].append(r[1])
                stamp(x, r[1])
        for x in people.values():
            x["visit_log"].sort(reverse=True)
    else:
        try:
            names = os.listdir(BASE)
        except OSError:
            names = []
        with _LOCK:
            for fn in names:
                d = _read(os.path.join(BASE, fn)) if fn.endswith(".json") else None
                if not d:
                    continue
                x = get(fn[:-5], d.get("name"))
                x["visit_log"] = list(d.get("visits", []))
                for h in d["items"]:
                    x["total"] += 1
                    x["by_kind"][h.get("k", "")] = x["by_kind"].get(h.get("k", ""), 0) + 1
                    stamp(x, f'{h.get("d", "")} {h.get("t", "")}'.strip())
                stamp(x, d.get("first", ""))
                stamp(x, d.get("last", ""))
    out = list(people.values())
    for x in out:
        x["visits"] = len(x["visit_log"])
    return sorted(out, key=lambda r: r["last"], reverse=True)


def recent(limit=12, force=False):
    """Hoạt động gần nhất của mọi học sinh: [{name, ts, k, q}], mới nhất trước.
    k rỗng nghĩa là một lần đăng nhập/truy cập; còn lại là lượt tra cứu (k = loại, q = nội dung)."""
    ev = []
    if _CFG:
        look, vis = _s_rows(force)
        for r in look:
            if r and slug(r[0]):
                it = _row_item(r)
                ev.append({"name": r[0], "ts": f'{it["d"]} {it["t"]}'.strip(), "k": it["k"], "q": it["q"]})
        for r in vis:
            if len(r) >= 2 and slug(r[0]):
                ev.append({"name": r[0], "ts": r[1], "k": "", "q": ""})
    else:
        try:
            names = os.listdir(BASE)
        except OSError:
            names = []
        with _LOCK:
            for fn in names:
                d = _read(os.path.join(BASE, fn)) if fn.endswith(".json") else None
                if not d:
                    continue
                nm = d.get("name") or fn[:-5]
                for h in d.get("items", []):
                    ev.append({"name": nm, "ts": f'{h.get("d", "")} {h.get("t", "")}'.strip(), "k": h.get("k", ""), "q": h.get("q", "")})
                for v in d.get("visits", []):
                    ev.append({"name": nm, "ts": v, "k": "", "q": ""})
    ev.sort(key=lambda e: e["ts"], reverse=True)
    return ev[:limit]


def students():
    """[(tên hiển thị, số lượt)] xếp theo tên."""
    return sorted([(r["name"], r["total"]) for r in summary()], key=lambda x: x[0].lower())


def delete(name):
    """Xóa hẳn dữ liệu của một học sinh (lượt tra cứu và lần truy cập)."""
    sl = slug(name)
    if not sl:
        return
    if _CFG:
        with _LOCK:
            look, vis = _s_rows(True)
            _s_call(lambda: _s_rewrite(look=[r for r in look if not (r and slug(r[0]) == sl)],
                                       vis=[r for r in vis if not (r and slug(r[0]) == sl)]))
        return
    p = _path(name)
    if p and os.path.exists(p):
        with _LOCK:
            os.remove(p)


def to_csv(rows, tab_of=None):
    """rows: [(học sinh, lượt)]. Trả về bytes CSV UTF-8 có BOM (mở được bằng Excel)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["hoc_sinh", "ngay", "gio", "tab", "loai", "noi_dung"])
    for who, h in rows:
        w.writerow([who, h.get("d", ""), h.get("t", ""), (tab_of(h.get("k")) if tab_of else ""), h.get("k", ""), h.get("q", "")])
    return buf.getvalue().encode("utf-8-sig")


# =====================================================================
# Bảng dùng chung cho lớp học (classes, accounts, assignments, submissions)
# Mỗi bảng là danh sách dòng (list các chuỗi), có dòng tiêu đề `head` trên Google Sheets.
# =====================================================================
def _tbl_local_path(name):
    return os.path.join(os.path.dirname(BASE), "tables", name + ".json")


def _tbl_ws(name, head):
    c = _TBL.setdefault(name, {"ws": None, "rows": None, "t": 0.0})
    if c["ws"] is None:
        c["ws"] = _get_ws(name, head)
    return c


def tbl_read(name, head, force=False):
    """Các dòng của bảng (không gồm tiêu đề). Google Sheets có bộ nhớ đệm ngắn hạn."""
    if _CFG:
        with _LOCK:
            c = _TBL.get(name)
            if c and c["rows"] is not None and not force and time.time() - c["t"] < _TTL:
                return [list(r) for r in c["rows"]]
            try:
                c = _tbl_ws(name, head)
                vals = _s_call(c["ws"].get_all_values)
            except OSError:
                raise
            except Exception as e:
                raise OSError(_set_err(e))
            c["rows"], c["t"] = [list(r) for r in vals[1:]], time.time()
            _ok()
            return [list(r) for r in c["rows"]]
    with _LOCK:
        try:
            with open(_tbl_local_path(name), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, list) else []
        except (OSError, ValueError):
            return []


def _set_err(e):
    global last_error
    last_error = _explain(e)
    return last_error


def _ok():
    """Một lần gọi Google Sheets thành công: xóa lỗi cũ để trạng thái kết nối hiện đúng."""
    global last_error
    last_error = ""


def tbl_append(name, head, row):
    row = [str(x) for x in row]
    if _CFG:
        with _LOCK:
            try:
                c = _tbl_ws(name, head)
                _s_call(lambda: c["ws"].append_row(row, value_input_option="RAW"))
            except OSError:
                raise
            except Exception as e:
                raise OSError(_set_err(e))
            if c["rows"] is not None:
                c["rows"].append(row)
            _ok()
        return
    with _LOCK:
        rows = tbl_read(name, head)
        rows.append(row)
        _tbl_save_local(name, rows)


def tbl_append_many(name, head, rows):
    """Thêm nhiều dòng một lần (một lệnh gọi Google Sheets), dùng cho tệp đính kèm chia thành nhiều mảnh."""
    rows = [[str(x) for x in r] for r in rows]
    if not rows:
        return
    if _CFG:
        with _LOCK:
            try:
                c = _tbl_ws(name, head)
                _s_call(lambda: c["ws"].append_rows(rows, value_input_option="RAW"))
            except OSError:
                raise
            except Exception as e:
                raise OSError(_set_err(e))
            if c["rows"] is not None:
                c["rows"].extend(rows)
            _ok()
        return
    with _LOCK:
        cur = tbl_read(name, head)
        cur.extend(rows)
        _tbl_save_local(name, cur)


def tbl_write(name, head, rows):
    """Thay toàn bộ nội dung bảng (dùng khi xóa/sửa, hiếm)."""
    rows = [[str(x) for x in r] for r in rows]
    if _CFG:
        with _LOCK:
            try:
                c = _tbl_ws(name, head)

                def go():
                    c["ws"].clear()
                    c["ws"].update(values=[head] + rows, range_name="A1")
                _s_call(go)
            except OSError:
                raise
            except Exception as e:
                raise OSError(_set_err(e))
            c["rows"], c["t"] = rows, time.time()
        return
    with _LOCK:
        _tbl_save_local(name, rows)


def _tbl_save_local(name, rows):
    p = _tbl_local_path(name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
