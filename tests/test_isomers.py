"""Kiểm toán logic sinh đồng phân bằng số liệu chuẩn độc lập (xem molsnap_core/isomers.py: GOLD_COUNTS và benchmarks/README.md)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from molsnap_core.isomers import GOLD_COUNTS, count_isomers, enumerate_isomers, parse_formula, scope_warnings, TooBig
from molsnap_core.parse import from_smiles
from molsnap_core.graph import canonical


class IsomerTests(unittest.TestCase):
    def test_so_luong_khop_so_lieu_chuan(self):
        for f, gold in GOLD_COUNTS.items():
            self.assertEqual(count_isomers(f, time_limit=120), gold, f)

    def test_tap_cau_truc_chua_cac_dong_phan_da_biet(self):
        """So sánh TẬP cấu trúc, không chỉ số lượng: C4H10O phải có đúng 4 ancol và 3 ete đã biết."""
        c, nH = parse_formula("C4H10O")
        got = enumerate_isomers(c, nH)
        known = ["CCCCO", "CC(C)CO", "CCC(C)O", "CC(C)(C)O", "CCOCC", "COCCC", "COC(C)C"]
        self.assertEqual(got, {canonical(from_smiles(s)) for s in known})

    def test_gioi_han_thoi_gian_bao_loi_thay_vi_tra_ket_qua_thieu(self):
        with self.assertRaises(TooBig):
            count_isomers("C14H30", time_limit=0.05)

    def test_phat_hien_dong_phan_nitro_nam_ngoai_pham_vi(self):
        """Hạn chế đã biết: nitroetan (N+ O-) không được sinh vì thuật toán chỉ dùng cấu trúc trung hòa với N hóa trị 3."""
        c, nH = parse_formula("C2H5NO2")
        got = enumerate_isomers(c, nH)
        nitroetan = from_smiles("CC[N+](=O)[O-]")
        self.assertNotIn(canonical(nitroetan), got)
        self.assertIn(canonical(from_smiles("NCC(=O)O")), got)        # glyxin có
        self.assertTrue(scope_warnings(c, nH))                         # và phải có cảnh báo trung thực

    def test_canh_bao_luu_huynh(self):
        self.assertTrue(scope_warnings({"C": 2, "S": 1, "O": 1}))
        self.assertEqual(scope_warnings({"C": 4, "O": 1}), [])

    def test_cong_thuc_khong_hop_le(self):
        for bad in ["", "abc", "C2H6X", "H2"]:
            with self.assertRaises(ValueError, msg=bad):
                parse_formula(bad)
        c, nH = parse_formula("CH5")
        self.assertEqual(enumerate_isomers(c, nH), set())


if __name__ == "__main__":
    unittest.main()
