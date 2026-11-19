import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from molsnap_core.parse import from_condensed as C, from_smiles as S
from molsnap_core.cvr import verify_and_diagnose, attribute_source, consensus, candidates_from
from molsnap_core import calibration as cal
from molsnap_core import evidence as ev

TG = S("CC(C)O")
OK, BAD, OTHER = C("CH3-CH(OH)-CH3"), C("CH3-C(OH)-CH3"), C("CH3-CH2-CH2-OH")


class CVRTests(unittest.TestCase):
    def run_case(self, cands, confirmed=False):
        return verify_and_diagnose(cands, TG, confirmed=confirmed)

    def test_ba_lan_doc_giong_nhau_cung_loi_hoa_tri_thi_quy_cho_hoc_sinh(self):
        r = self.run_case([BAD, BAD.copy(), BAD.copy()])
        self.assertEqual((r["trang_thai"], r["nguon"], r["tinh_huong"]), ("sai", "hoc_sinh", "hoc_sinh_khong_hop_le"))

    def test_cau_truc_hop_le_nhung_sai_de(self):
        r = self.run_case([OTHER, OTHER.copy(), OTHER.copy()])
        self.assertEqual((r["trang_thai"], r["tinh_huong"], r["loi_chinh"]), ("sai", "hop_le_sai_yeu_cau", "sai_vi_tri_nhom_chuc"))

    def test_dung(self):
        r = self.run_case([OK, OK.copy()])
        self.assertEqual((r["trang_thai"], r["tinh_huong"]), ("dung", "dung"))

    def test_cac_lan_doc_bat_dong_thi_khong_ket_luan(self):
        """Không được tự chọn một kết quả rồi tuyên bố: phải từ chối và yêu cầu xác nhận."""
        for cands in ([BAD, OK, BAD.copy()], [OK, OTHER], [BAD, C("CH3-C-CH2-OH")]):
            r = self.run_case(cands)
            self.assertEqual(r["trang_thai"], "khong_du_thong_tin")
            self.assertTrue(r["can_xac_nhan"])
            self.assertNotIn("sai_hoa_tri", [e["ma"] for e in r["loi"]])

    def test_may_doc_nham_duoc_nhan_dien(self):
        r = self.run_case([BAD, OK, BAD.copy()])
        self.assertEqual(r["nguon"], "nhan_dang_ai")

    def test_mot_lan_doc_chua_xac_nhan_thi_tu_choi_con_da_xac_nhan_thi_cham(self):
        self.assertEqual(self.run_case([BAD])["trang_thai"], "khong_du_thong_tin")
        r = self.run_case([BAD], confirmed=True)
        self.assertEqual((r["trang_thai"], r["nguon"]), ("sai", "hoc_sinh"))

    def test_that_bai_hoan_toan_khong_tu_tao_ket_qua(self):
        r = self.run_case([None, None])
        self.assertEqual(r["trang_thai"], "khong_du_thong_tin")
        self.assertEqual(r["so_lan_doc"], 0)

    def test_chi_kiem_tra_hop_le_khong_co_de(self):
        r = verify_and_diagnose([BAD, BAD.copy()], None)
        self.assertEqual(r["trang_thai"], "sai")
        self.assertEqual(verify_and_diagnose([OK, OK.copy()], None)["trang_thai"], "hop_le")

    def test_candidates_from_chiu_du_lieu_xau(self):
        good = {"atoms": [{"id": 1, "el": "C", "h": 4}], "bonds": []}
        cands, warns, fails = candidates_from([good, {"atoms": []}, "rac"], ["C", "C(C"])
        self.assertEqual(len([c for c in cands if c is not None]), 2)   # 1 đồ thị tốt + 1 SMILES đọc được
        self.assertEqual(fails, 3)

    def test_vector_bat_dong(self):
        c = consensus([OK, OK.copy(), BAD])
        self.assertAlmostEqual(c["dong_thuan"], 2 / 3)
        self.assertAlmostEqual(c["vector"]["phat_hoa_tri"], 1 / 3)
        self.assertEqual(consensus([OK, OK.copy()])["vector"]["bat_dong_cau_truc"], 0.0)


class CalibrationTests(unittest.TestCase):
    def test_brier_va_ece_gia_tri_da_biet(self):
        self.assertAlmostEqual(cal.brier([1.0, 0.0], [1, 0]), 0.0)
        self.assertAlmostEqual(cal.brier([0.5, 0.5], [1, 0]), 0.25)
        self.assertAlmostEqual(cal.ece([0.9] * 10, [1] * 9 + [0]), 0.0)          # đúng 90% khi nói 0,9: hiệu chuẩn hoàn hảo
        self.assertAlmostEqual(cal.ece([0.9] * 10, [1] * 5 + [0] * 5), 0.4)      # nói 0,9 nhưng chỉ đúng 50%

    def test_logistic_hoc_duoc_du_lieu_tach_duoc(self):
        rnd = random.Random(0)
        X = [[rnd.random()] for _ in range(200)]
        y = [1 if x[0] > 0.5 else 0 for x in X]
        m = cal.fit_logistic(X, y, l2=0.1, iters=1500, lr=1.0)
        acc = sum((cal.predict_proba(m, x) > 0.5) == bool(t) for x, t in zip(X, y)) / len(y)
        self.assertGreater(acc, 0.9)

    def test_dang_huong_don_dieu(self):
        model = cal.isotonic_fit([1, 2, 3, 4, 5, 6], [0, 1, 0, 0, 1, 1])
        ps = [cal.isotonic_predict(model, s) for s in range(1, 7)]
        self.assertEqual(ps, sorted(ps))

    def test_phu_va_chinh_xac_theo_nguong(self):
        out = cal.coverage_accuracy([0.9, 0.8, 0.6, 0.55], [1, 1, 0, 1], [0.5, 0.7])
        self.assertEqual(out[0][1], 1.0)
        self.assertAlmostEqual(out[1][1], 0.5)
        self.assertEqual(out[1][2], 1.0)

    def test_nguong_tu_choi_neu_khong_dat_muc_tieu(self):
        self.assertIsNone(cal.choose_threshold([0.9, 0.8, 0.7], [0, 0, 1], 0.95))
        self.assertEqual(cal.choose_threshold([0.9, 0.8, 0.3], [1, 1, 0], 0.95), 0.8)


class EvidenceTests(unittest.TestCase):
    def test_prf_khong_bia_so_khi_mau_so_bang_0(self):
        r = ev.binary_prf([0, 0, 0], [0, 0, 0])
        self.assertIsNone(r["precision"]); self.assertIsNone(r["f1"])

    def test_ca_khong_du_can_cu_dem_rieng(self):
        cases = [{"id": "a", "dap_an_loi": ["x"]}, {"id": "b", "dap_an_loi": []}, {"id": "c", "dap_an_loi": ["y"]}]
        outs = {"a": {"trang_thai": "sai", "loi": [{"ma": "x"}]}, "b": {"trang_thai": "dung", "loi": []}, "c": {"trang_thai": "khong_du_thong_tin", "loi": []}}
        rows, s = ev.run_diagnosis_benchmark(cases, lambda c: outs[c["id"]])
        self.assertEqual((s["so_ca"], s["so_ca_duoc_ket_luan"], s["khong_du_can_cu"]), (3, 2, 1))
        self.assertAlmostEqual(s["do_phu"], 2 / 3)
        self.assertEqual(s["khop_tuyet_doi"], 1.0)

    def test_loi_he_thong_khong_lam_hong_ca_benchmark(self):
        def boom(c):
            raise ValueError("x")
        rows, s = ev.run_diagnosis_benchmark([{"id": "a", "dap_an_loi": []}], boom)
        self.assertEqual(rows[0]["ket_qua"], ev.NO_BASIS)
        self.assertEqual(rows[0]["loi_he_thong"], "ValueError")

    def test_csv_co_dong_cau_hinh_va_doc_lai_duoc(self):
        meta = ev.run_metadata({"mo_hinh": "thu"})
        text = ev.to_csv([{"a": 1, "b": "x"}], meta)
        self.assertTrue(text.startswith("# {"))
        self.assertEqual(ev.load_cases_csv(text), [{"a": "1", "b": "x"}])

    def test_nhan_dang_anh_so_do_thi_chuan(self):
        row = ev.recognition_row("k", OK, OK.copy())
        self.assertEqual(row["ket_qua"], "dung")
        self.assertEqual(ev.recognition_row("k", OK, OTHER)["khop_cong_thuc"], True)
        self.assertEqual(ev.recognition_row("k", OK, OTHER)["khop_cau_tao"], False)
        self.assertEqual(ev.recognition_row("k", OK, None)["ket_qua"], ev.NO_BASIS)


if __name__ == "__main__":
    unittest.main()


class StatsTests(unittest.TestCase):
    def test_kappa_gia_tri_da_biet(self):
        self.assertEqual(ev.cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]), 1.0)
        self.assertAlmostEqual(ev.cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]), 0.0)
        self.assertAlmostEqual(ev.cohen_kappa(["a", "a", "a", "b", "b", "b"], ["a", "a", "b", "b", "b", "b"]), 2 / 3, places=6)
        self.assertIsNone(ev.cohen_kappa([], []))
        self.assertIsNone(ev.cohen_kappa(["a", "a"], ["a", "a"]))     # không biến thiên: không định nghĩa

    def test_wilson(self):
        lo, hi = ev.wilson_ci(8, 10)
        self.assertAlmostEqual(lo, 0.4902, places=3)
        self.assertAlmostEqual(hi, 0.9433, places=3)
        self.assertIsNone(ev.wilson_ci(0, 0))
        lo, hi = ev.wilson_ci(10, 10)
        self.assertEqual(hi, 1.0)

    def test_bootstrap_chua_trung_binh_va_tai_lap_duoc(self):
        v = [0, 1, 1, 1, 0, 1, 1, 0, 1, 1]
        a, b = ev.bootstrap_ci(v, seed=1), ev.bootstrap_ci(v, seed=1)
        self.assertEqual(a, b)
        self.assertLessEqual(a[0], 0.7)
        self.assertGreaterEqual(a[1], 0.7)
        self.assertIsNone(ev.bootstrap_ci([]))

    def test_prf_nguyen_tu_va_lien_ket(self):
        r = ev.graph_multiset_prf(OK, OK.copy())
        self.assertEqual(r["nguyen_tu"]["f1"], 1.0)
        self.assertEqual(r["lien_ket"]["f1"], 1.0)
        r = ev.graph_multiset_prf(OK, OTHER)       # cùng nguyên tử, khác vị trí nhóm OH
        self.assertLess(r["nguyen_tu"]["f1"], 1.0)  # số H trên từng C khác nhau


if __name__ == "__main__" and False:
    pass
