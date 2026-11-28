"""Kiểm thử logic hoạt động / tiến độ / thành thạo. Chạy: python tests/test_hoat_dong.py (tự làm trên bản sao, không đụng dữ liệu thật)."""
import os, shutil, sys, tempfile, threading, time
src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); work = os.path.join(tmp, "p"); shutil.copytree(src, work, ignore=shutil.ignore_patterns("tests", "__pycache__"))
os.chdir(work); sys.path.insert(0, work)
import classroom as cr, history_store as hs

ok = []
def check(name, cond):
    ok.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name)

T = cr.make_auth(cr.TEACHER)
def new(title="B"): return cr.create_assignment(T, "11A1", title, [], "2026-11-20", True, "2026-11-10 08:00")
S = lambda n: cr.make_auth(cr.STUDENT, "11A1", n)
K = lambda n: hs.slug(cr.identity("11A1", n))

# 1. Tiến độ theo trọng số
aid = new(); cr.set_activities(T, aid, [dict(name="Đọc", auto="tay", weight=1, topic="X", level="nb"), dict(name="Quiz", auto="quiz", weight=2, topic="X", level="vd", pass_pct=60), dict(name="Phụ", auto="tay", req=False)])
cr.set_questions(T, aid, 2, [dict(q="a", options=["A. 1", "B. 2"], answer="B")])
cr.mark_activity(S("An"), aid, 1, True, "t"); cr.submit_quiz(S("An"), aid, 2, ["B"], "2026-11-12 09:00")
acts, st = cr.activity_states(T, aid); cells = st[K("An")]
check("tiến độ có trọng số = 100% khi xong mọi hoạt động bắt buộc", cr.progress_pct(acts, cells) == 100)
cr.set_activities(T, aid, [dict(name=a["name"], auto=a["auto"], weight=1 if a["n"] == 1 else 3, topic=a["topic"], level=a["level"], pass_pct=a["pass_pct"], req=a["req"]) for a in acts])
acts, st = cr.activity_states(T, aid); cr.mark_activity(S("Binh"), aid, 1, True, "t")
acts, st = cr.activity_states(T, aid)
check("Bình xong HĐ1 (trọng số 1/4) = 25%", cr.progress_pct(acts, st[K("Binh")]) == 25)
check("mở/bấm hoạt động không tự hoàn thành (HĐ quiz chưa nộp)", st[K("Binh")][2]["st"] == "chua")
# 2. Thành thạo
check("thành thạo chưa đủ dữ liệu khi <2 kết quả", cr.mastery(acts, st[K("An")])[1] is None)
# 3. Quiz: không lộ đáp án, giới hạn số lần, đồng thời
aid2 = new("Q"); cr.set_activities(T, aid2, [dict(name="Q1", auto="quiz", tries=2, due="2026-11-11")])
cr.set_questions(T, aid2, 1, [dict(q="2+2", options=[], answer="4;bốn")])
check("học sinh không nhận đáp án", all("answer" not in q for q in cr.questions(S("An"), aid2, 1)))
check("đáp án ngắn nhiều cách viết", cr.submit_quiz(S("An"), aid2, 1, ["bốn"], "2026-11-12 10:00")["pct"] == 100)
res = []
def go():
    try: cr.submit_quiz(S("Cuong"), aid2, 1, ["4"], "t"); res.append(1)
    except cr.Denied: pass
ts = [threading.Thread(target=go) for _ in range(6)]; [t.start() for t in ts]; [t.join() for t in ts]
check("nộp đồng thời không vượt số lần (2)", len(res) == 2)
check("quá hạn đánh dấu muộn", cr.attempts(T, aid2)[0]["late"] is True)
check("giáo viên cho làm lại", cr.reset_attempts(T, aid2, cr.identity("11A1", "An")) >= 0 and not cr.attempts(T, aid2, cr.identity("11A1", "An")))
# 4. Nộp tệp theo hoạt động + chấm
aid3 = new("F"); cr.set_activities(T, aid3, [dict(name="F1", auto="tep"), dict(name="F2", auto="tep")])
cr.submit_activity_file(S("An"), aid3, 2, "a.pdf", "application/pdf", b"%PDF-1 x", "t")
acts, st = cr.activity_states(T, aid3)
check("tệp nộp cho HĐ2 chỉ tính HĐ2", st[K("An")][1]["st"] == "chua" and st[K("An")][2]["st"] == "cho")
cr.grade_activity(T, aid3, 2, cr.identity("11A1", "An"), 80, "", "t"); acts, st = cr.activity_states(T, aid3)
check("giáo viên chấm đạt -> hoàn thành", st[K("An")][2]["st"] == "xong")
# 5. AI review: riêng tư, không điểm cho học sinh
fid = cr.activity_submission_files(S("An"), aid3, 2)[0]["id"]
cr.save_review(S("An"), aid3, 2, fid, {"diem_de_xuat": 55, "loi_sai": [{"loi": "sai", "muc_do": "x"}]}, "t")
check("học sinh không thấy điểm AI, người khác không thấy nhận xét", "diem" not in cr.reviews(S("An"), aid3, 2)[0] and cr.reviews(S("Binh"), aid3, 2) == [])
# 6. Phân quyền
try: cr.set_activities(S("An"), aid, []); check("học sinh không sửa được hoạt động", False)
except cr.Denied: check("học sinh không sửa được hoạt động", True)
try: cr.mark_activity(S("An"), aid, 2, True, "t"); check("không tự bấm hoạt động tự chấm", False)
except cr.Denied: check("không tự bấm hoạt động tự chấm", True)
# 7. Tổng quan + quá hạn
rows = cr.overview(acts, st, [cr.identity("11A1", "An"), cr.identity("11A1", "Zed")], "2026-11-20", "2026-11-28")
check("ma trận: chưa làm quá hạn = đỏ", rows[1]["cells"][1] == "qua_han" and rows[0]["cells"][2] == "xong")
# 8. Phân tích JSON của AI
a1, q1 = cr.parse_ai_activities('```json\n{"hoat_dong":[{"name":"A","type":"Lạ","weight":-3,"questions":[{"q":"Q","options":["x"],"answer":"A"}]}]}\n```')
check("JSON AI được làm sạch", a1[0]["type"] == "Bài tập vận dụng" and a1[0]["weight"] == 0.1 and len(q1["A"]) == 1)
for bad in ("xin chào", '{"hoat_dong": []}'):
    try: cr.parse_ai_activities(bad); check("JSON AI hỏng bị từ chối", False)
    except ValueError: check("JSON AI hỏng bị từ chối", True)
# 9. Dự phòng khi Google Sheets hết hạn mức
hs._CFG = ("id", {}); hs._TBL["x"] = {"ws": None, "rows": [["a"]], "t": time.time() - 999}
def boom(n, h): raise OSError("429")
hs._tbl_ws = boom
check("hết hạn mức đọc: dùng bản đã nhớ", hs.tbl_read("x", ["a"]) == [["a"]])
print(f"\n{sum(ok)}/{len(ok)} kiểm thử đạt"); shutil.rmtree(tmp, ignore_errors=True); sys.exit(0 if all(ok) else 1)
