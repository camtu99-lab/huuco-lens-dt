import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from molsnap_core.parse import from_condensed as C
from molsnap_core.exercises import EXERCISES
from molsnap_core.diagnose import diagnose
from molsnap_core.coach import hints_for
from molsnap_core.session import PracticeSession
from molsnap_core.store import Store, anonymize
from molsnap_core.adapt import next_exercise, skill_profile, current_level

EX = {e.ten: e for e in EXERCISES}


class CoachTests(unittest.TestCase):
    CASES = [("CH3-CH2-CH2-OH", "propan-2-ol"), ("CH3-CH(CH3)-CH2-OH", "butan-1-ol"), ("CH3-CH2-CH3", "propen"), ("CH3-C-CH3", "propan-2-ol"),
             ("CH3-O-CH3", "etanol"), ("CH2=CH-CH2-CH3", "but-2-en"), ("CH3-CH3-OH", "etanol"), ("CH3-CH2-CH3", "butan"), ("CH2=CH-CH2-CH3", "2-metylpropan")]

    def test_ba_muc_rieng_cho_tung_loi_va_khong_lo_dap_an(self):
        for stu, name in self.CASES:
            ex = EX[name]
            r = diagnose(C(stu), ex.graph)
            e = r["loi"][0]
            hs = hints_for(e, ex.ten)
            self.assertEqual(len(hs), 3, (stu, e["ma"]))
            self.assertEqual(len(set(hs)), 3)
            for h in hs:
                self.assertGreater(len(h), 30)
                self.assertNotIn(ex.smiles, h)          # không lộ cấu trúc đáp án dạng mã
            self.assertNotIn(ex.formula, hs[0])         # mức 1 không nêu công thức phân tử của đáp án

    def test_noi_dung_goi_y_khac_nhau_giua_cac_loai_loi(self):
        first = {}
        for stu, name in self.CASES:
            e = diagnose(C(stu), EX[name].graph)["loi"][0]
            first.setdefault(e["ma"], hints_for(e, name)[0])
        self.assertGreaterEqual(len(set(first.values())), 6)

    def test_khong_du_thong_tin_khong_co_goi_y(self):
        e = {"ma": "khong_du_thong_tin", "chi_tiet": {}}
        self.assertIsNone(hints_for(e))

    def test_goi_y_3_vi_tri_nhom_chuc_noi_ro_cacbon(self):
        e = diagnose(C("CH3-CH2-CH2-OH"), EX["propan-2-ol"].graph)["loi"][0]
        self.assertIn("cacbon số 1", hints_for(e, "propan-2-ol")[2])
        self.assertIn("cacbon số 2", hints_for(e, "propan-2-ol")[2])


class SessionTests(unittest.TestCase):
    def test_kich_ban_ve_sai_goi_y_sua_kiem_tra_luu(self):
        t = [0.0]
        s = PracticeSession(EX["propan-2-ol"], clock=lambda: t.__setitem__(0, t[0] + 1) or t[0])
        r = s.submit(C("CH3-CH2-CH2-OH"))
        self.assertEqual(r["loi_chinh"], "sai_vi_tri_nhom_chuc")
        self.assertFalse(s.can_reveal())
        with self.assertRaises(RuntimeError):
            s.reveal()
        self.assertEqual([s.next_hint()["muc"] for _ in range(3)], [1, 2, 3])
        self.assertIsNone(s.next_hint())
        self.assertTrue(s.can_reveal())
        r2 = s.submit(C("CH3-CH(OH)-CH3"))
        self.assertEqual(r2["trang_thai"], "dung")
        sm = s.summary()
        self.assertEqual((sm["result"], sm["n_submissions"], sm["n_fixes"], sm["hints"], sm["max_level"]), ("sua_dung_sau_goi_y", 2, 1, 3, 3))
        db = Store()
        hs = anonymize("lan.12a", "muoi")
        db.save_attempt(hs, sm)
        got = db.attempts_of(hs)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["errors"], ["sai_vi_tri_nhom_chuc"])
        with self.assertRaises(RuntimeError):
            s.submit(C("CH3-CH(OH)-CH3"))      # lượt đã kết thúc

    def test_tu_sua_dung_khong_goi_y(self):
        s = PracticeSession(EX["etanol"])
        s.submit(C("CH3-CH3-OH"))
        s.submit(C("CH3-CH2-OH"))
        self.assertEqual(s.summary()["result"], "tu_sua_dung")

    def test_xem_dap_an_sau_ba_lan_sai(self):
        s = PracticeSession(EX["etanol"])
        for _ in range(3):
            s.submit(C("CH3-O-CH3"))
        self.assertTrue(s.can_reveal())
        self.assertEqual(s.reveal()["ten"], "etanol")
        self.assertEqual(s.summary()["result"], "xem_dap_an")

    def test_lan_nop_khong_du_thong_tin_khong_tinh_la_loi_hoc_sinh(self):
        s = PracticeSession(EX["etanol"])
        from molsnap_core.graph import MolGraph
        g = MolGraph()
        g.add_atom("C", 3); g.add_atom("C", 3)       # hai nguyên tử rời nhau
        r = s.submit(g)
        self.assertEqual(r["trang_thai"], "khong_du_thong_tin")
        self.assertIsNone(s.next_hint())
        self.assertEqual(s.summary()["errors"], [])


class StoreAdaptTests(unittest.TestCase):
    def test_an_danh_va_xoa(self):
        a, b = anonymize("Lan", "x"), anonymize(" lan ", "x")
        self.assertEqual(a, b)
        self.assertNotIn("lan", a.lower().replace("hs_", ""))
        self.assertEqual(anonymize("", "x"), "an_danh")
        db = Store()
        s = PracticeSession(EX["etanol"]); s.submit(C("CH3-CH2-OH"))
        db.save_attempt(a, s.summary())
        db.delete_student(a)
        self.assertEqual(db.attempts_of(a), [])

    def test_xuat_va_nap_lai_csv(self):
        db = Store()
        s = PracticeSession(EX["etanol"]); s.submit(C("CH3-CH3-OH")); s.next_hint(); s.submit(C("CH3-CH2-OH"))
        db.save_attempt("hs_x", s.summary())
        text = db.export_csv()
        db2 = Store()
        self.assertEqual(db2.import_csv(text), 1)
        self.assertEqual(db2.attempts_of("hs_x")[0]["hints"], 1)

    def test_quy_tac_chon_bai_minh_bach(self):
        # học sinh mắc lỗi vị trí nhóm chức -> được đề xuất bài luyện đúng kỹ năng đó
        db = Store()
        s = PracticeSession(EX["propan-2-ol"]); s.submit(C("CH3-CH2-CH2-OH")); [s.next_hint() for _ in range(3)]; s.submit(C("CH3-CH(OH)-CH3"))
        db.save_attempt("hs_x", s.summary())
        att = db.attempts_of("hs_x")
        ex, why = next_exercise(att)
        self.assertIn("sai_vi_tri_nhom_chuc", ex.skills)
        self.assertNotEqual(ex.ten, "propan-2-ol")
        self.assertGreater(skill_profile(att)["sai_vi_tri_nhom_chuc"]["diem_yeu"], skill_profile(att)["sai_mach_cacbon"]["diem_yeu"])

    def test_muc_kho_tang_giam(self):
        mk = lambda r: {"exercise_id": "ex00", "errors": [], "result": r}
        self.assertEqual(current_level([mk("tu_sua_dung")] * 3), 2)
        self.assertEqual(current_level([mk("tu_sua_dung")] * 6), 3)
        self.assertEqual(current_level([mk("tu_sua_dung")] * 3 + [mk("xem_dap_an")]), 1)
        self.assertEqual(current_level([mk("xem_dap_an")]), 1)
        self.assertEqual(current_level([mk("tu_sua_dung")] * 2 + [mk("sua_dung_sau_goi_y")] + [mk("tu_sua_dung")] * 2), 1)


if __name__ == "__main__":
    unittest.main()
