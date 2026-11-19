"""Chạy thử luồng giao diện CVR bằng Streamlit GIẢ (không cần cài streamlit): mô phỏng bấm nút, rerun và kiểm tra nội dung hiển thị.
Phần này kiểm tra LOGIC luồng; hình thức hiển thị thật phải xem bằng Streamlit (xem tests/test_ui_smoke.py và báo cáo kiểm thử)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from molsnap_core import ui
from molsnap_core.exercises import EXERCISES
from molsnap_core.parse import from_condensed as C
from molsnap_core.store import Store, anonymize

EX = {e.ten: e for e in EXERCISES}


class Rerun(Exception):
    pass


class File:
    def __init__(self, b):
        self.b = b

    def getvalue(self):
        return self.b


class Ctx:
    def __init__(self, st):
        self.st = st

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __getattr__(self, name):
        return getattr(self.st, name)


class FakeSt:
    def __init__(self):
        self.session_state, self.values, self.presses, self.out = {}, {}, set(), []

    def _o(self, kind, *a):
        self.out.append((kind, " ".join(str(x) for x in a)))

    def text(self):
        return "\n".join(f"{k}: {v}" for k, v in self.out)

    def radio(self, label, options, key=None, **k):
        return self.values.get(key, options[0])

    def file_uploader(self, label, key=None, **k):
        v = self.values.get(key)
        return File(v) if v else None

    camera_input = file_uploader

    def text_input(self, label, key=None, **k):
        return self.values.get(key, "")

    def button(self, label, key=None, disabled=False, **k):
        self._o("button", label)
        return (key in self.presses) and not disabled

    def columns(self, n, **k):
        return [Ctx(self) for _ in range(n if isinstance(n, int) else len(n))]

    def expander(self, *a, **k):
        return Ctx(self)

    def spinner(self, *a, **k):
        return Ctx(self)

    def data_editor(self, data, key=None, **k):
        return self.values.get(key, data)

    def rerun(self):
        raise Rerun()

    def __getattr__(self, name):
        if name in ("markdown", "info", "warning", "success", "error", "caption", "code", "image"):
            return lambda *a, **k: self._o(name, *a)
        raise AttributeError(name)


class Deps:
    def __init__(self, readings=None, fail=False, budget=True):
        self.readings, self.fail, self.budget, self.spent, self.saved = readings or [], fail, budget, 0, []

    def read_graphs(self, img):
        if self.fail:
            raise RuntimeError("API lỗi")
        return self.readings, ["nét liên kết hơi mờ"]

    def draw(self, g, bad):
        return b"IMG"

    def draw_smiles(self, s):
        return b"IMG"

    def budget_ok(self):
        return self.budget

    def spend(self, n):
        self.spent += n

    def save_attempt(self, summary):
        self.saved.append(summary)


def drive(st, deps, exercise=None, key="cvr", presses=(), values=None):
    """Một lần 'bấm' của học sinh: chạy lại script cho tới khi hết rerun, trả về (kết quả cuối, toàn bộ nội dung hiển thị lần chạy cuối)."""
    st.values.update(values or {})
    st.presses = set(presses)
    for _ in range(8):
        st.out = []
        try:
            r = ui.render(st, deps, exercise, key)
            st.presses = set()
            return r
        except Rerun:
            st.presses = set()
    raise AssertionError("rerun không dừng")


def dump(g):
    return ui.graph_to_dict(g)


WRONG = dump(C("CH3-CH2-CH2-OH"))
RIGHT = dump(C("CH3-CH(OH)-CH3"))
BAD_VALENCE = dump(C("CH3-C(OH)-CH3"))


class FlowTests(unittest.TestCase):
    def test_kich_ban_tieu_chi_thanh_cong(self):
        """Học sinh vẽ sai -> chụp ảnh -> xác nhận -> MolSnap giải thích lỗi -> gợi ý -> tự sửa -> kiểm chứng lại -> lưu tiến bộ."""
        st, deps = FakeSt(), Deps([WRONG, WRONG])
        ex = EX["propan-2-ol"]
        drive(st, deps, ex, values={"cvr_up": b"anh"}, presses=["cvr_go"])
        self.assertIn("MolSnap đọc được hình em vẽ", st.text())
        self.assertIn("Ảnh gốc của em", st.text())
        self.assertEqual(deps.spent, 2)
        drive(st, deps, ex, presses=["cvr_ok"])
        txt = st.text()
        self.assertIn("Sai vị trí nhóm chức", txt)
        self.assertIn("Gợi ý 1", txt)
        self.assertNotIn("Đáp án", txt)                                    # chưa lộ đáp án
        drive(st, deps, ex, presses=["cvr_hint0_0"])
        self.assertIn("Gợi ý 1: tự tìm chỗ sai", st.text())
        drive(st, deps, ex, presses=["cvr_hint0_1"])
        drive(st, deps, ex, presses=["cvr_hint0_2"])
        self.assertIn("Gợi ý 3: cách sửa", st.text())
        self.assertIn("cacbon số 2", st.text())
        r = drive(st, deps, ex, presses=["cvr_resub0"])
        self.assertIn("Lần nộp thứ 2", st.text())
        r = drive(st, deps, ex, values={"cvr_how": "⌨️ Gõ công thức thu gọn", "cvr_txt": "CH3-CH(OH)-CH3"}, presses=["cvr_go"])
        self.assertTrue(r["hoan_thanh"])
        self.assertIn("Đã kiểm tra lại: đúng", st.text())
        self.assertEqual(len(deps.saved), 1)
        sm = deps.saved[0]
        self.assertEqual((sm["result"], sm["n_submissions"], sm["hints"], sm["max_level"]), ("sua_dung_sau_goi_y", 2, 3, 3))
        drive(st, deps, ex)       # rerun thêm lần nữa không được lưu trùng
        self.assertEqual(len(deps.saved), 1)

    def test_may_doc_bat_dong_thi_canh_bao_va_cho_hoc_sinh_xac_nhan(self):
        st, deps = FakeSt(), Deps([BAD_VALENCE, RIGHT])
        drive(st, deps, EX["propan-2-ol"], values={"cvr_up": b"anh"}, presses=["cvr_go"])
        self.assertIn("Máy có thể đã đọc nhầm", st.text())
        self.assertIn("MolSnap chỉ chấm bài sau khi em xác nhận", st.text())

    def test_loi_api_khong_tu_tao_ket_qua(self):
        st, deps = FakeSt(), Deps(fail=True)
        drive(st, deps, EX["etanol"], values={"cvr_up": b"anh"}, presses=["cvr_go"])
        self.assertIn("không tự đoán kết quả", st.text())
        self.assertEqual(st.session_state["cvr_s"]["stage"], "nhap")

    def test_het_luot_ai(self):
        st, deps = FakeSt(), Deps(budget=False)
        drive(st, deps, EX["etanol"], values={"cvr_up": b"anh"}, presses=["cvr_go"])
        self.assertIn("hết số lượt", st.text())
        self.assertEqual(deps.spent, 0)

    def test_go_cong_thuc_sai_cu_phap(self):
        st, deps = FakeSt(), Deps()
        drive(st, deps, EX["etanol"], values={"cvr_how": "⌨️ Gõ công thức thu gọn", "cvr_txt": "CH3-CH2-"}, presses=["cvr_go"])
        self.assertIn("chưa viết đúng", st.text())
        self.assertEqual(st.session_state["cvr_s"]["stage"], "nhap")

    def test_hoc_sinh_tu_chinh_cau_truc_bang_cong_thuc_thu_gon(self):
        st, deps = FakeSt(), Deps([BAD_VALENCE, BAD_VALENCE])
        ex = EX["propan-2-ol"]
        drive(st, deps, ex, values={"cvr_up": b"anh"}, presses=["cvr_go"])
        r = drive(st, deps, ex, values={"cvr_retype": "CH3-CH(OH)-CH3"}, presses=["cvr_edit_go"])
        self.assertTrue(r["hoan_thanh"])
        self.assertEqual(deps.saved[0]["result"], "tu_sua_dung")

    def test_chinh_bang_bang_nguyen_tu_va_lien_ket(self):
        st, deps = FakeSt(), Deps([BAD_VALENCE, BAD_VALENCE])
        ex = EX["propan-2-ol"]
        drive(st, deps, ex, values={"cvr_up": b"anh"}, presses=["cvr_go"])
        atoms = [{"Mã": a["id"], "Nguyên tố": a["el"], "Số H": (a["h"] or 0) + (1 if a["el"] == "C" and a["h"] == 0 else 0)} for a in BAD_VALENCE["atoms"]]
        bonds = [{"Từ nguyên tử": b[0], "Đến nguyên tử": b[1], "Bậc": b[2]} for b in BAD_VALENCE["bonds"]]
        r = drive(st, deps, ex, values={"cvr_ea": atoms, "cvr_eb": bonds}, presses=["cvr_edit_go"])
        self.assertTrue(r["hoan_thanh"])          # C giữa thêm 1 H -> propan-2-ol đúng

    def test_che_do_khong_de_bai_chi_kiem_tra_hoa_tri_va_van_co_goi_y(self):
        st, deps = FakeSt(), Deps()
        drive(st, deps, None, key="free", values={"free_how": "⌨️ Gõ công thức thu gọn", "free_txt": "CH3-CH3-OH"}, presses=["free_go"])
        self.assertIn("Sai hóa trị", st.text())
        for k in range(3):
            drive(st, deps, None, key="free", presses=[f"free_hint0_{k}"])
        self.assertIn("Gợi ý 3: cách sửa", st.text())
        drive(st, deps, None, key="free")
        self.assertIn("hết 3 gợi ý", st.text())
        drive(st, deps, None, key="free", presses=["free_resub0"], values={})
        r = drive(st, deps, None, key="free", values={"free_txt": "CH3-CH2-OH"}, presses=["free_go"])
        self.assertTrue(r["hoan_thanh"])
        self.assertIn("hợp lệ về hóa trị", st.text())
        self.assertEqual(deps.saved, [])           # không có đề thì không lưu lượt luyện tập

    def test_khong_xem_dap_an_som(self):
        st, deps = FakeSt(), Deps()
        ex = EX["etanol"]
        drive(st, deps, ex, values={"cvr_how": "⌨️ Gõ công thức thu gọn", "cvr_txt": "CH3-O-CH3"}, presses=["cvr_go"])
        self.assertNotIn("Xem đáp án", "\n".join(v for k, v in st.out if k == "button"))
        self.assertIn("mới xem được đáp án", st.text())


if __name__ == "__main__":
    unittest.main()
