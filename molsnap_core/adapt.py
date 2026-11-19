"""MolSnap Adapt: hồ sơ kỹ năng và chọn bài theo quy tắc minh bạch (không dùng học máy).

Quy tắc, ghi rõ để giải thích được cho học sinh và hội đồng:
  1. Với mỗi kỹ năng s: cơ hội = số lượt làm các bài có thể gây lỗi s; lỗi = số lượt thực sự mắc lỗi s.
     Điểm yếu(s) = (lỗi + 1) / (cơ hội + 2)  (làm mịn Laplace để ít dữ liệu không cho kết quả cực đoan).
  2. Chọn kỹ năng yếu nhất trong các kỹ năng đã từng mắc lỗi; chọn bài chưa làm gần đây có kỹ năng đó, độ khó gần mức hiện tại.
  3. Mức khó: bắt đầu 1; tự sửa đúng liên tiếp 3 bài thì tăng 1 mức; xem đáp án thì giảm 1 mức; sửa đúng sau gợi ý giữ nguyên.
"""
from .exercises import EXERCISES, BY_ID, ALL_SKILLS

LEVEL_MAX = 4
RECENT = 6


def skill_profile(attempts):
    prof = {s: {"co_hoi": 0, "loi": 0} for s in ALL_SKILLS}
    for a in attempts:
        ex = BY_ID.get(a["exercise_id"])
        if not ex:
            continue
        for s in ex.skills:
            if s in prof:
                prof[s]["co_hoi"] += 1
        for m in a["errors"]:
            if m in prof:
                prof[m]["loi"] += 1
    for v in prof.values():
        v["diem_yeu"] = round((v["loi"] + 1) / (v["co_hoi"] + 2), 3)
    return prof


def current_level(attempts):
    level, streak = 1, 0
    for a in attempts:
        if a["result"] == "tu_sua_dung":
            streak += 1
            if streak >= 3 and level < LEVEL_MAX:
                level, streak = level + 1, 0
        elif a["result"] == "xem_dap_an":
            level, streak = max(1, level - 1), 0
        elif a["result"] == "sua_dung_sau_goi_y":
            streak = 0
    return level


def next_exercise(attempts, exclude=()):
    """Trả về (bài, lý do bằng tiếng Việt) theo các quy tắc ở đầu tệp."""
    level = current_level(attempts)
    recent = {a["exercise_id"] for a in attempts[-RECENT:]} | set(exclude)
    prof = skill_profile(attempts)
    weak = sorted((s for s, v in prof.items() if v["loi"] > 0), key=lambda s: (-prof[s]["diem_yeu"], s))
    for s in weak:
        pool = [e for e in EXERCISES if s in e.skills and e.id not in recent and abs(e.difficulty - level) <= 1]
        if pool:
            pool.sort(key=lambda e: (abs(e.difficulty - level), e.idx))
            return pool[0], f"Em hay mắc lỗi '{s}', bài này luyện đúng kỹ năng đó (mức khó {pool[0].difficulty})."
    done = {a["exercise_id"] for a in attempts}
    pool = [e for e in EXERCISES if e.id not in recent and e.difficulty == level] or [e for e in EXERCISES if e.id not in recent]
    pool.sort(key=lambda e: (e.id in done, abs(e.difficulty - level), e.idx))
    e = pool[0] if pool else EXERCISES[0]
    return e, ("Bài mới ở mức khó " + str(e.difficulty) + (" (em đang làm tốt, tăng dần độ khó)." if level > 1 else "."))
