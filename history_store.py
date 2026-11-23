"""Lưu lịch sử tra cứu của từng học sinh vào tệp JSON (thư mục data/history/).

Mỗi học sinh một tệp: {"name": "Nguyễn An", "items": [{"q","k","d","t","p"?}, ...]} (mới nhất đứng đầu).
Không dùng streamlit để dễ kiểm thử. Ghi tệp an toàn (ghi tệp tạm rồi đổi tên) và có khóa luồng.
Lưu ý khi triển khai: ổ đĩa của Streamlit Community Cloud bị xóa khi ứng dụng khởi động lại,
nên hãy dùng nút "Tải lịch sử (CSV)" để sao lưu, hoặc đặt HISTORY_DIR trỏ tới ổ đĩa bền vững.
"""
import csv
import io
import json
import os
import re
import tempfile
import threading
import unicodedata

BASE = os.environ.get("HISTORY_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "history")
MAX_KEEP = 300          # số lượt tối đa giữ cho mỗi học sinh
_LOCK = threading.Lock()


def slug(name):
    """Tên không dấu, chữ thường, chỉ gồm a-z 0-9 và _ (rỗng nếu không có tên)."""
    s = unicodedata.normalize("NFD", (name or "").lower().replace("đ", "d"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:40]


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


def load(name):
    """Danh sách lượt tra cứu của học sinh (mới nhất trước). Rỗng nếu chưa có hoặc không có tên."""
    p = _path(name)
    if not p:
        return []
    with _LOCK:
        d = _read(p)
    return d["items"] if d else []


def save(name, items):
    p = _path(name)
    if not p:
        return False
    with _LOCK:
        _write(p, {"name": name.strip(), "items": items[:MAX_KEEP]})
    return True


def append(name, entry):
    """Thêm một lượt vào đầu danh sách; bỏ qua nếu trùng hệt lượt liền trước. Trả về True nếu đã ghi."""
    p = _path(name)
    if not p:
        return False
    with _LOCK:
        d = _read(p) or {"name": name.strip(), "items": []}
        items = d["items"]
        if items and items[0].get("q") == entry.get("q") and items[0].get("k") == entry.get("k"):
            return False
        items.insert(0, entry)
        del items[MAX_KEEP:]
        d["name"] = name.strip()
        _write(p, d)
    return True


def clear(name, kinds=None):
    """Xóa toàn bộ lịch sử, hoặc chỉ các lượt thuộc những loại trong `kinds`."""
    p = _path(name)
    if not p:
        return
    with _LOCK:
        d = _read(p)
        if not d:
            return
        d["items"] = [] if kinds is None else [h for h in d["items"] if h.get("k") not in set(kinds)]
        _write(p, d)


def students():
    """[(tên hiển thị, số lượt)] của tất cả học sinh có tệp, xếp theo tên."""
    out = []
    try:
        names = os.listdir(BASE)
    except OSError:
        return out
    with _LOCK:
        for fn in names:
            if fn.endswith(".json"):
                d = _read(os.path.join(BASE, fn))
                if d:
                    out.append((d.get("name") or fn[:-5], len(d["items"])))
    return sorted(out, key=lambda x: x[0].lower())


def to_csv(rows, tab_of=None):
    """rows: [(học sinh, lượt)]. Trả về bytes CSV UTF-8 có BOM (mở được bằng Excel)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["hoc_sinh", "ngay", "gio", "tab", "loai", "noi_dung"])
    for who, h in rows:
        w.writerow([who, h.get("d", ""), h.get("t", ""), (tab_of(h.get("k")) if tab_of else ""), h.get("k", ""), h.get("q", "")])
    return buf.getvalue().encode("utf-8-sig")
