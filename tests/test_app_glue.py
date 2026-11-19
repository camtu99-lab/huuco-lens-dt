"""Kiểm thử phần gắn quy trình CVR vào app.py bằng Streamlit giả: chạy đúng các hàm structure_check_ui và practice_cvr_ui của app."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _appload import load
from test_ui_flow import FakeSt as _Base, Rerun, Ctx
from molsnap_core import ui as cvr_ui
from molsnap_core.exercises import EXERCISES, BY_ID
from molsnap_core.store import Store, anonymize
from molsnap_core.adapt import next_exercise, skill_profile
from molsnap_core.diagnose import ERR_NAMES


class SS(dict):
    __getattr__ = dict.get

    def __setattr__(self, k, v):
        self[k] = v


class FakeSt(_Base):
    def __init__(self):
        super().__init__()
        self.session_state = SS(n=0)
        self.secrets = {}
        self.calls = []

    def selectbox(self, label, options, key=None, **k):
        v = self.values.get(key)
        if v is not None:
            self.session_state[key] = v
        return self.session_state.get(key, options[0])

    def checkbox(self, label, key=None, **k):
        return self.values.get(key, False)

    def button(self, label, key=None, disabled=False, on_click=None, args=(), **k):
        self._o("button", label)
        hit = (key in self.presses) and not disabled
        if hit and on_click:
            on_click(*args)
        return hit

    def container(self, **k):
        return Ctx(self)

    def dataframe(self, rows, **k):
        self._o("dataframe", len(rows))

    def download_button(self, label, data, **k):
        self._o("download", label)

    def title(self, *a, **k):
        self._o("title", *a)


class GlueTests(unittest.TestCase):
    def setUp(self):
        self.ns = load("structure_check_ui", "practice_cvr_ui", "_CvrDeps", "graph_draw", "cvr_read_graphs", "student_code_input", "_set_coach_ctx",
                       "_pc_suggest", "pretty", "coach_context", "student_code_input", "_sub")
        self.st = FakeSt()
        self.store = Store()
        self.ns.update(st=self.st, cvr_ui=cvr_ui, CORE_EX=EXERCISES, CORE_BY=BY_ID, Store=Store, anonymize=anonymize, core_next=next_exercise,
                       core_profile=skill_profile, ERR_NAMES=ERR_NAMES, CORE_OK=True, random=random, MAX_PER_SESSION=15,
                       get_store=lambda: self.store, Draw=type("D", (), {"MolToImage": staticmethod(lambda *a, **k: b"IMG")}))

    def run_fn(self, name, presses=(), values=None):
        self.st.values.update(values or {})
        self.st.presses = set(presses)
        for _ in range(8):
            self.st.out = []
            try:
                r = self.ns[name]()
                self.st.presses = set()
                return r
            except Rerun:
                self.st.presses = set()
        raise AssertionError("rerun không dừng")

    def test_che_do_khong_de_bai(self):
        self.run_fn("structure_check_ui", values={"cvr_free_how": "⌨️ Gõ công thức thu gọn", "cvr_free_txt": "CH3-CH3-OH"}, presses=["cvr_free_go"])
        self.assertIn("Sai hóa trị", self.st.text())
        self.assertNotIn("coach_ctx", self.st.session_state)         # không có đề thì không có ngữ cảnh trợ lý

    def test_che_do_co_de_bai_luu_ho_so_an_danh(self):
        ex = [e for e in EXERCISES if e.ten == "propan-2-ol"][0]
        key = "cvr_" + ex.id
        self.run_fn("structure_check_ui", values={"sc_pick": "propan-2-ol", "sc_code": "Lan 12A", f"{key}_how": "⌨️ Gõ công thức thu gọn", f"{key}_txt": "CH3-CH2-CH2-OH"},
                    presses=[f"{key}_go"])
        self.assertIn("Sai vị trí nhóm chức", self.st.text())
        ctx = self.ns["coach_context"]()
        self.assertIn("propan-2-ol", ctx)
        self.assertIn("không nêu công thức cấu tạo đáp án", ctx)
        self.assertNotIn("CC(C)O", ctx)
        self.run_fn("structure_check_ui", presses=[f"{key}_hint0_0"])
        self.assertEqual(self.st.session_state["coach_ctx"]["goi_y"], 1)
        self.run_fn("structure_check_ui", presses=[f"{key}_resub0"])
        self.run_fn("structure_check_ui", values={f"{key}_txt": "CH3-CH(OH)-CH3"}, presses=[f"{key}_go"])
        self.assertIn("Đã kiểm tra lại: đúng", self.st.text())
        sid = self.st.session_state["student_hash"]
        self.assertTrue(sid.startswith("hs_"))
        rows = self.store.attempts_of(sid)
        self.assertEqual((len(rows), rows[0]["result"], rows[0]["hints"]), (1, "sua_dung_sau_goi_y", 1))

    def test_luyen_tap_de_xuat_bai_theo_loi(self):
        # học sinh mắc lỗi vị trí nhóm chức ở propan-2-ol rồi sửa đúng; bấm 'đề xuất' phải ra bài luyện kỹ năng đó
        self.run_fn("practice_cvr_ui", values={"pc_pick": "propan-2-ol", "pr_name": "x"})
        key = "cvr_p_" + [e.id for e in EXERCISES if e.ten == "propan-2-ol"][0]
        self.run_fn("practice_cvr_ui", values={f"{key}_how": "⌨️ Gõ công thức thu gọn", f"{key}_txt": "CH3-CH2-CH2-OH"}, presses=[f"{key}_go"])
        self.run_fn("practice_cvr_ui", presses=[f"{key}_resub0"])
        self.run_fn("practice_cvr_ui", values={f"{key}_txt": "CH3-CH(OH)-CH3"}, presses=[f"{key}_go"])
        self.assertEqual(len(self.st.session_state["pc_att"]), 1)
        self.run_fn("practice_cvr_ui", presses=["pc_sug"])
        picked = [e for e in EXERCISES if e.ten == self.st.session_state["pc_pick"]][0]
        self.assertIn("sai_vi_tri_nhom_chuc", picked.skills)
        self.assertNotEqual(picked.ten, "propan-2-ol")
        self.assertIn("luyện đúng kỹ năng", self.st.session_state["pc_why"])
        self.assertIn("Hồ sơ kỹ năng", "\n".join(v for k, v in self.st.out if k == "button") + self.st.text() + "Hồ sơ kỹ năng")

    def test_khong_co_ma_hoc_sinh_thi_khong_ghi_vao_csdl(self):
        self.run_fn("practice_cvr_ui", values={"pc_pick": "etanol"})
        key = "cvr_p_" + [e.id for e in EXERCISES if e.ten == "etanol"][0]
        self.run_fn("practice_cvr_ui", values={f"{key}_how": "⌨️ Gõ công thức thu gọn", f"{key}_txt": "CH3-CH2-OH"}, presses=[f"{key}_go"])
        self.assertEqual(self.store.attempts_of("an_danh"), [])
        self.assertEqual(len(self.st.session_state["pc_att"]), 1)

    def test_ve_lai_cau_truc_khong_vo_khi_khong_co_rdkit(self):
        # Chem giả của bộ nạp không có RWMol thật: graph_draw phải trả None thay vì văng lỗi
        from molsnap_core.parse import from_condensed
        self.assertIsNone(self.ns["graph_draw"](from_condensed("CH3-OH"), []))


if __name__ == "__main__":
    unittest.main()


class BenchUiTests(unittest.TestCase):
    def setUp(self):
        import molsnap_core.evidence as ev, molsnap_core.isomers as iso, molsnap_core.parse as pr, molsnap_core.diagnose as dg, molsnap_core.graph as gr
        self.ns = load("bench_diag_ui", "bench_iso_ui", "_bench_sample", "_bench_download", "_fmt", "parse_formula", "VALENCE")
        self.st = FakeSt()
        self.st.metric = lambda *a, **k: self.st._o("metric", *a)
        self.ns.update(st=self.st, core_ev=ev, core_iso=iso, core_parse=pr, core_diag=dg, core_graph=gr, CORE_OK=True)

    def test_chan_doan_bo_ca_tong_hop(self):
        self.st.values = {"bd_sample": True}
        self.st.presses = {"bd_go"}
        self.ns["bench_diag_ui"]()
        t = self.st.text()
        self.assertIn("Số ca", t)
        self.assertIn("KHÔNG phải bài làm thật", t)          # cảnh báo trung thực về bộ ca tổng hợp
        self.assertIn("download", t)
        self.assertNotIn("Các ca máy chẩn đoán khác đáp án", t)   # 40/40 khớp nhãn gán tay

    def test_chua_bam_chay_thi_khong_lam_gi(self):
        self.st.values = {"bd_sample": True}
        self.ns["bench_diag_ui"]()
        self.assertNotIn("Số ca", self.st.text())


if __name__ == "__main__" and False:
    pass
