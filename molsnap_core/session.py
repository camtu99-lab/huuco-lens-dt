"""Máy trạng thái một lượt luyện tập: nộp bài, nhận gợi ý, sửa, nộp lại, xem đáp án.

Không phụ thuộc Streamlit: lớp này giữ toàn bộ logic để kiểm thử được độc lập, giao diện chỉ hiển thị kết quả.
"""
import time
from .diagnose import diagnose
from .coach import hints_for, HINT_LEVELS

MIN_SUBMISSIONS_TO_REVEAL = 3


class PracticeSession:
    def __init__(self, exercise, clock=time.time):
        self.ex, self.clock = exercise, clock
        self.started = clock()
        self.finished = None
        self.subs = []              # mỗi lần nộp
        self.hint_level = {}        # mã lỗi -> mức gợi ý cao nhất đã xem cho lỗi đó
        self.hints_total = 0
        self.max_level = 0
        self.revealed = False
        self.solved = False
        self.last = None            # kết quả chẩn đoán gần nhất

    # ---- nộp bài ----
    def submit(self, student, source="nhap_tay", confirmed=True, warnings=()):
        if self.finished:
            raise RuntimeError("Lượt luyện tập này đã kết thúc.")
        res = diagnose(student, self.ex.graph, confirmed=confirmed, warnings=warnings)
        self.last = res
        self.subs.append({"ts": self.clock(), "nguon": source, "ket_qua": res["trang_thai"], "loi_chinh": res["loi_chinh"],
                          "muc_goi_y": self.max_level, "ma_loi": [e["ma"] for e in res["loi"]]})
        if res["trang_thai"] == "dung":
            self.solved = True
            self.finished = self.clock()
        return res

    # ---- gợi ý ----
    def current_error(self):
        if not self.last or self.last["trang_thai"] != "sai":
            return None
        return next((e for e in self.last["loi"] if e["ma"] == self.last["loi_chinh"]), None)

    def can_hint(self):
        e = self.current_error()
        return bool(e) and self.hint_level.get(e["ma"], 0) < HINT_LEVELS and hints_for(e) is not None

    def next_hint(self):
        """Gợi ý kế tiếp cho lỗi chính hiện tại; None nếu hết gợi ý hoặc chưa có lỗi đã xác minh."""
        if self.finished or not self.can_hint():
            return None
        e = self.current_error()
        lvl = self.hint_level.get(e["ma"], 0) + 1
        self.hint_level[e["ma"]] = lvl
        self.hints_total += 1
        self.max_level = max(self.max_level, lvl)
        if self.subs:
            self.subs[-1]["muc_goi_y"] = self.max_level
        return {"muc": lvl, "ma": e["ma"], "noi_dung": hints_for(e, self.ex.ten)[lvl - 1], "con_lai": HINT_LEVELS - lvl}

    # ---- xem đáp án ----
    def can_reveal(self):
        if self.finished:
            return False
        e = self.current_error()
        seen_all = bool(e) and self.hint_level.get(e["ma"], 0) >= HINT_LEVELS
        return seen_all or len([s for s in self.subs if s["ket_qua"] == "sai"]) >= MIN_SUBMISSIONS_TO_REVEAL

    def reveal(self):
        if not self.can_reveal():
            raise RuntimeError("Hãy dùng gợi ý hoặc thử sửa thêm trước khi xem đáp án.")
        self.revealed = True
        self.finished = self.clock()
        return {"ten": self.ex.ten, "ct_phan_tu": self.ex.formula, "smiles": self.ex.smiles}

    # ---- tóm tắt để lưu hồ sơ ----
    def summary(self):
        end = self.finished or self.clock()
        wrong = [s for s in self.subs if s["ket_qua"] == "sai"]
        errors = []
        for s in self.subs:
            for m in s["ma_loi"]:
                if s["ket_qua"] == "sai" and m not in errors:
                    errors.append(m)
        if self.solved:
            result = "tu_sua_dung" if self.hints_total == 0 else "sua_dung_sau_goi_y"
        elif self.revealed:
            result = "xem_dap_an"
        else:
            result = "chua_xong"
        return {"exercise_id": self.ex.id, "started": self.started, "finished": self.finished, "seconds": round(end - self.started, 1),
                "n_submissions": len(self.subs), "n_fixes": max(0, len(self.subs) - 1), "hints": self.hints_total, "max_level": self.max_level,
                "result": result, "errors": errors, "first_error": (wrong[0]["loi_chinh"] if wrong else None),
                "submissions": [{"ts": s["ts"], "source": s["nguon"], "outcome": s["ket_qua"], "primary_error": s["loi_chinh"], "hint_level": s["muc_goi_y"]} for s in self.subs]}
