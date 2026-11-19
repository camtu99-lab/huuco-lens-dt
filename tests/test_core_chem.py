import itertools
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from molsnap_core.graph import MolGraph, canonical, same_structure, carbon_chain
from molsnap_core.parse import from_smiles, from_condensed, from_ai_graph, ParseError
from molsnap_core.exercises import EXERCISES


def relabel(g, seed):
    """Cùng phân tử nhưng đánh số nguyên tử ngẫu nhiên khác."""
    ids = list(g.atoms)
    perm = ids[:]
    random.Random(seed).shuffle(perm)
    m = dict(zip(ids, perm))
    h = MolGraph()
    for i in perm:
        h.add_atom("C", None, id=i)
    h.atoms = {}
    for i, a in g.atoms.items():
        h.add_atom(a.el, a.h, a.charge, id=m[i])
    for b, o in g.bonds.items():
        i, j = tuple(b)
        h.add_bond(m[i], m[j], o)
    return h


class GraphTests(unittest.TestCase):
    def test_hoa_tri_va_cong_thuc(self):
        g = from_condensed("CH3-CH2-OH")
        self.assertEqual(g.hill(), "C2H6O")
        self.assertEqual(g.valence_issues(), [])

    def test_phat_hien_thua_va_thieu_hoa_tri(self):
        thua = from_condensed("CH3-CH(CH3)(CH3)-CH3")
        self.assertTrue(any(v["loai"] == "thua" and v["el"] == "C" for v in thua.valence_issues()))
        thieu = from_condensed("CH3-C-CH3")
        self.assertTrue(any(v["loai"] == "thieu" for v in thieu.valence_issues()))

    def test_khong_tu_sua_cau_truc_sai(self):
        """Cấu trúc sai phải được giữ nguyên, không bị chuẩn hóa thành cấu trúc đúng."""
        g = from_condensed("CH3-C-CH3")
        self.assertEqual(g.formula()["H"], 6)   # đúng 6 H học sinh viết, không tự thêm H

    def test_dang_chuan_bat_bien_khi_danh_so_lai(self):
        for smi in ["CC(C)O", "CC(C)(C)C", "Oc1ccccc1", "OCC(O)CO", "CCOC(C)=O", "ClC(Cl)Cl"]:
            g = from_smiles(smi)
            for seed in range(4):
                self.assertEqual(canonical(g), canonical(relabel(g, seed)), smi)

    def test_dang_chuan_phan_biet_dong_phan(self):
        self.assertNotEqual(canonical(from_smiles("CCCO")), canonical(from_smiles("CC(C)O")))
        self.assertNotEqual(canonical(from_smiles("CCO")), canonical(from_smiles("COC")))
        self.assertNotEqual(canonical(from_smiles("C=CCC")), canonical(from_smiles("CC=CC")))

    def test_benzen_hai_dang_kekule_la_mot(self):
        a = from_smiles("c1ccccc1")
        b = from_smiles("C1=CC=CC=C1")
        self.assertEqual(canonical(a), canonical(b))

    def test_mach_chinh(self):
        self.assertEqual(len(carbon_chain(from_smiles("CC(C)CC"))), 4)
        self.assertEqual(len(carbon_chain(from_smiles("CC(C)(C)C"))), 3)
        self.assertIsNone(carbon_chain(from_smiles("C1CCCC1")))


class ParseTests(unittest.TestCase):
    GOLD = {"CC(C)O": "C3H8O", "C=CC": "C3H6", "C#C": "C2H2", "OCC(O)CO": "C3H8O3", "CC(=O)O": "C2H4O2", "CCOC(C)=O": "C4H8O2",
            "NCC(=O)O": "C2H5NO2", "c1ccccc1": "C6H6", "Cc1ccccc1": "C7H8", "ClC(Cl)Cl": "CHCl3", "[NH3+]CC([O-])=O": "C2H5NO2"}

    def test_smiles_cong_thuc_chuan(self):
        for smi, f in self.GOLD.items():
            self.assertEqual(from_smiles(smi).hill(), f, smi)

    def test_cong_thuc_thu_gon(self):
        gold = {"CH3-CH2-CH2-OH": "C3H8O", "CH3-CH(OH)-CH3": "C3H8O", "CH3COOH": "C2H4O2", "HCOOCH3": "C2H4O2", "CH3-CO-CH3": "C3H6O",
                "CH2=CH-CH3": "C3H6", "CH3-CHO": "C2H4O", "CHCl3": "CHCl3", "CH3-CH(CH3)-CH3": "C4H10", "CH3NH2": "CH5N"}
        for t, f in gold.items():
            self.assertEqual(from_condensed(t).hill(), f, t)

    def test_cung_chat_hai_cach_viet(self):
        self.assertEqual(canonical(from_condensed("CH3-CH(OH)-CH3")), canonical(from_smiles("CC(C)O")))
        self.assertEqual(canonical(from_condensed("CH3COOCH3")), canonical(from_smiles("COC(C)=O")))

    def test_loi_cu_phap_khong_bi_im_lang(self):
        for bad in ["CH3-CH2-", "CH3-(", "", "CH3-CH2-X", "CH3)", "CH3-2"]:
            with self.assertRaises(ParseError, msg=bad):
                from_condensed(bad)
        for bad in ["C(C", "C1CC", "C)C", "[Xx]C", ""]:
            with self.assertRaises(ParseError, msg=bad):
                from_smiles(bad)

    def test_do_thi_ai_loi_du_lieu(self):
        g, w = from_ai_graph({"atoms": [{"id": 1, "el": "c", "h": 3}, {"id": 2, "el": "O", "h": 1}], "bonds": [[1, 2, 1], [1, 9, 1], [1, 1, 1]]})
        self.assertEqual(g.hill(), "CH4O")
        self.assertGreaterEqual(len(w), 2)       # liên kết tới nguyên tử không tồn tại, liên kết vòng về chính nó
        with self.assertRaises(ParseError):
            from_ai_graph({"atoms": [], "bonds": []})
        with self.assertRaises(ParseError):
            from_ai_graph("không phải dict")

    def test_do_thi_ai_roi_nhau_bi_canh_bao(self):
        g, w = from_ai_graph({"atoms": [{"id": 1, "el": "C", "h": 3}, {"id": 2, "el": "C", "h": 3}], "bonds": []})
        self.assertTrue(any("rời" in x for x in w))


class ExerciseBankTests(unittest.TestCase):
    def test_cong_thuc_chuan_viet_tay_khop_cau_truc(self):
        """Công thức phân tử chuẩn do người soạn nhập độc lập; phát hiện lỗi gõ trong SMILES của ngân hàng bài."""
        for e in EXERCISES:
            self.assertEqual(e.graph.hill(), e.formula, e.ten)
            self.assertEqual(e.graph.valence_issues(), [], e.ten)
            self.assertTrue(e.graph.is_connected(), e.ten)

    def test_khong_trung_cau_truc(self):
        keys = [canonical(e.graph) for e in EXERCISES]
        self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
    unittest.main()
