"""Kiểm thử hồi quy các hàm thuần Python trong app.py (không cần Streamlit, RDKit hay mạng)."""
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _appload import load


class AppPure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load("sim_clean", "sim_balance", "sim_match_builtin", "SIM_BUILTINS", "_equation_side", "_formula_atoms", "rx_balanced",
                      "norm_params", "pass_filters", "redox_analysis", "_norm_formula", "SIM_TEMPLATE", "to_int")

    def test_khop_thi_nghiem_co_san_khong_nuot_chat_la(self):
        m = self.ns["sim_match_builtin"]
        self.assertIsNone(m("Gly-Ala-Gly + CuSO4+ NaOH"))
        self.assertEqual(m("CuSO4 + NaOH"), "cuso4_naoh")
        self.assertEqual(m("Thí nghiệm CuSO4 tác dụng với NaOH"), "cuso4_naoh")
        self.assertEqual(m("Nhiệt phân KMnO4 thu khí oxi"), "kmno4")
        self.assertIsNone(m("kẽm + HCl + CuSO4"))

    def test_kiem_tra_can_bang_phuong_trinh(self):
        b = self.ns["sim_balance"]
        yes = ["CuSO4 + 2NaOH → Cu(OH)2↓ + Na2SO4", "Zn + 2HCl -> ZnCl2 + H2↑", "2KMnO4 -> K2MnO4 + MnO2 + O2↑", "2Al + 6HCl -> 2AlCl3 + 3H2↑"]
        no = ["Zn + HCl -> ZnCl2 + H2", "Al + 3HCl -> AlCl3 + H2"]
        for e in yes:
            self.assertTrue(b({"phuong_trinh": e}), e)
        for e in no:
            self.assertFalse(b({"phuong_trinh": e}), e)
        for e in ["", "Fe3+ + 3OH- -> Fe(OH)3", "A ⇌ B"]:
            self.assertIsNone(b({"phuong_trinh": e}), e)

    def test_sim_clean_chuan_hoa_va_tu_choi(self):
        c = self.ns["sim_clean"]
        sc, err = c({"ten": "T", "dung_cu": [{"id": "A", "loai": "xyz"}], "buoc": [{"mo_ta": "m", "hanh_dong": [
            {"loai": "them_long", "dung_cu": "Q", "mau": "hong", "muc": 5}, {"loai": "bay"}]}]})
        self.assertIsNone(err)
        a = sc["buoc"][0]["hanh_dong"]
        self.assertEqual(len(a), 1)                           # hành động lạ bị loại
        self.assertEqual(a[0]["dung_cu"], "A")                # dụng cụ không tồn tại về dụng cụ đầu
        self.assertRegex(a[0]["mau"], r"^#[0-9a-f]{6}$")      # màu sai được thay bằng màu hợp lệ
        self.assertLessEqual(a[0]["muc"], 0.8)
        for bad in [None, [], {"tu_choi": "nguy hiểm"}, {"buoc": [{"hanh_dong": []}]}]:
            self.assertIsNotNone(c(bad)[1], bad)

    def test_mau_phim_khong_con_cho_giu_cho_va_co_co_giao(self):
        t = self.ns["SIM_TEMPLATE"]
        self.assertEqual(t.count("__DATA__"), 1)
        self.assertIn("teacherPose", t)
        self.assertIn("mouthOpen", t)

    def test_tai_ba_thi_nghiem_co_san_hop_le(self):
        B = self.ns["SIM_BUILTINS"]
        self.assertEqual(len(B), 6)
        for k, sc in B.items():
            self.assertTrue(sc["buoc"], k)
            self.assertTrue(self.ns["sim_balance"]({"phuong_trinh": sc["phuong_trinh"]}) in (True, None), k)

    def test_loc_dong_phan_theo_tinh_chat(self):
        norm, pf = self.ns["norm_params"], self.ns["pass_filters"]

        class M:
            def __init__(s, sm): s.sm = set(sm)
            def HasSubstructMatch(s, pt): return pt[1] in s.sm
            def GetRingInfo(s):
                class R:
                    def NumRings(self): return 0
                return R()
            def GetAtoms(s): return []
        self.ns["func_units"] = lambda m: 1
        mols = {"axit": M(["[OX2H]", "[CX3](=O)[OX2H1]"]), "este": M(["[CX3](=O)[OX2][#6]"]), "hidroxi-andehit": M(["[OX2H]", "[CX3H1]=O"]), "ete": M([])}
        run = lambda raw: [n for n, m in mols.items() if pf(m, [], norm(raw)[0])]
        self.assertEqual(run({"phan_ung": ["NaOH", "Na"], "kieu_phan_ung": "tat_ca"}), ["axit"])
        self.assertEqual(run({"phan_ung": ["NaOH"], "khong_phan_ung": ["Na"]}), ["este"])
        self.assertEqual(run({"phan_ung": ["AgNO3/NH3"]}), ["hidroxi-andehit"])

    def test_phan_tich_oxi_hoa_khu(self):
        ns = self.ns
        ns["_species_atoms_charge"] = lambda sp: (dict(ns["_atoms"](sp["cong_thuc"])), sp.get("charge", 0))
        ra = ns["redox_analysis"]
        sp = lambda f, c=1: {"he_so": c, "cong_thuc": f, "smiles": "x"}
        ent = lambda f, *e: {"cong_thuc": f, "nguyen_to": [{"kh": a, "so": b, "n": c} for a, b, c in e]}
        r = {"chat_tham_gia": [sp("Zn"), sp("HCl", 2)], "san_pham": [sp("ZnCl2"), sp("H2")],
             "oxi_hoa_khu": {"so_oxi_hoa": [ent("Zn", ("Zn", 0, 1)), ent("HCl", ("H", 1, 1), ("Cl", -1, 1)), ent("ZnCl2", ("Zn", 2, 1), ("Cl", -1, 2)), ent("H2", ("H", 0, 2))]}}
        a = ra(r)
        self.assertTrue(a["ok"] and a["redox"])
        self.assertEqual([x[0] for x in a["khu"]], ["Zn"])
        self.assertEqual([x[0] for x in a["oxh"]], ["HCl"])
        r["oxi_hoa_khu"]["so_oxi_hoa"][0] = ent("Zn", ("Zn", 2, 1))     # AI đưa số oxi hóa sai: phải bị bắt
        self.assertFalse(ra(r)["ok"])


if __name__ == "__main__":
    unittest.main()
