"""Hồ sơ học tập bằng SQLite. Chỉ lưu mã học sinh ẩn danh (băm có muối), không lưu tên, không lưu ảnh."""
import csv
import hashlib
import io
import json
import os
import sqlite3

SCHEMA_VERSION = 1
_DDL = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS attempts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, student TEXT NOT NULL, exercise_id TEXT NOT NULL, started REAL, finished REAL, seconds REAL,
  n_submissions INTEGER, n_fixes INTEGER, hints INTEGER, max_level INTEGER, result TEXT, errors TEXT, first_error TEXT);
CREATE TABLE IF NOT EXISTS submissions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  ts REAL, source TEXT, outcome TEXT, primary_error TEXT, hint_level INTEGER);
CREATE INDEX IF NOT EXISTS ix_att_student ON attempts(student);
"""


def anonymize(code, salt=""):
    """Mã học sinh ẩn danh. Không có mã thì dùng 'an_danh' (không gom được tiến bộ giữa các phiên)."""
    code = (code or "").strip().lower()
    if not code:
        return "an_danh"
    return "hs_" + hashlib.sha256((salt + "|" + code).encode("utf-8")).hexdigest()[:10]


class Store:
    def __init__(self, path=":memory:"):
        self.path, self.persistent = path, path != ":memory:"
        if self.persistent:
            try:
                d = os.path.dirname(os.path.abspath(path))
                os.makedirs(d, exist_ok=True)
                self._c = sqlite3.connect(path, check_same_thread=False)
            except Exception:
                self.path, self.persistent = ":memory:", False
                self._c = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._c = sqlite3.connect(":memory:", check_same_thread=False)
        self._c.execute("PRAGMA foreign_keys=ON")
        self._c.executescript(_DDL)
        self._c.execute("INSERT OR IGNORE INTO meta VALUES('schema', ?)", (str(SCHEMA_VERSION),))
        self._c.commit()

    def save_attempt(self, student, summary):
        cur = self._c.execute(
            "INSERT INTO attempts(student, exercise_id, started, finished, seconds, n_submissions, n_fixes, hints, max_level, result, errors, first_error)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (student, summary["exercise_id"], summary["started"], summary["finished"], summary["seconds"], summary["n_submissions"], summary["n_fixes"],
             summary["hints"], summary["max_level"], summary["result"], json.dumps(summary["errors"]), summary["first_error"]))
        aid = cur.lastrowid
        self._c.executemany("INSERT INTO submissions(attempt_id, ts, source, outcome, primary_error, hint_level) VALUES(?,?,?,?,?,?)",
                            [(aid, s["ts"], s["source"], s["outcome"], s["primary_error"], s["hint_level"]) for s in summary["submissions"]])
        self._c.commit()
        return aid

    def attempts_of(self, student):
        rows = self._c.execute("SELECT id, exercise_id, started, seconds, n_submissions, n_fixes, hints, max_level, result, errors, first_error "
                               "FROM attempts WHERE student=? ORDER BY id", (student,)).fetchall()
        keys = ["id", "exercise_id", "started", "seconds", "n_submissions", "n_fixes", "hints", "max_level", "result", "errors", "first_error"]
        out = []
        for r in rows:
            d = dict(zip(keys, r))
            d["errors"] = json.loads(d["errors"] or "[]")
            out.append(d)
        return out

    def delete_student(self, student):
        """Xóa toàn bộ dữ liệu của một học sinh (quyền được xóa)."""
        self._c.execute("DELETE FROM attempts WHERE student=?", (student,))
        self._c.commit()

    def export_csv(self, student=None):
        q = "SELECT student, exercise_id, started, seconds, n_submissions, n_fixes, hints, max_level, result, errors, first_error FROM attempts"
        args = ()
        if student:
            q, args = q + " WHERE student=?", (student,)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ma_hoc_sinh", "ma_bai", "bat_dau", "giay", "so_lan_nop", "so_lan_sua", "so_goi_y", "muc_goi_y_cao_nhat", "ket_qua", "cac_loi", "loi_dau_tien"])
        w.writerows(self._c.execute(q + " ORDER BY id", args).fetchall())
        return buf.getvalue()

    def import_csv(self, text):
        """Nạp lại tệp CSV đã xuất (khi máy chủ khởi động lại làm mất cơ sở dữ liệu). Trả về số dòng nạp được."""
        n = 0
        for r in csv.DictReader(io.StringIO(text)):
            try:
                errs = r.get("cac_loi") or "[]"
                json.loads(errs)
                self._c.execute("INSERT INTO attempts(student, exercise_id, started, seconds, n_submissions, n_fixes, hints, max_level, result, errors, first_error)"
                                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                (r["ma_hoc_sinh"], r["ma_bai"], float(r["bat_dau"] or 0), float(r["giay"] or 0), int(r["so_lan_nop"]), int(r["so_lan_sua"]),
                                 int(r["so_goi_y"]), int(r["muc_goi_y_cao_nhat"]), r["ket_qua"], errs, r["loi_dau_tien"] or None))
                n += 1
            except Exception:
                continue
        self._c.commit()
        return n
