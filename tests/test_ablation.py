"""Kiểm thử MÃ đối chứng bằng dữ liệu TỔNG HỢP. Dữ liệu dưới đây do người soạn dựng để thử logic, KHÔNG phải kết quả của Gemini và
không được dùng để nói gì về độ chính xác của Gemini hay MolSnap."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from molsnap_core import ablation as ab
from molsnap_core.parse import from_condensed as C
from molsnap_core.ui import graph_to_dict

OKG, BADG, WRONGPOS = (graph_to_dict(C(x)) for x in ("CH3-CH(OH)-CH3", "CH3-C(OH)-CH3", "CH3-CH2-CH2-OH"))
CASES = [{"id": "m1", "dap_an_smiles": "CC(C)O", "dap_an_loi": [], "do_thi_chuan_smiles": "CC(C)O"},
         {"id": "m2", "dap_an_smiles": "CC(C)O", "dap_an_loi": ["sai_vi_tri_nhom_chuc"], "do_thi_chuan_smiles": "CCCO"},
         {"id": "m3", "dap_an_smiles": "CC(C)O", "dap_an_loi": ["sai_hoa_tri"], "do_thi_chuan_smiles": "CC(C)O"},
         {"id": "m4", "dap_an_smiles": "CC(C)O", "dap_an_loi": []}]            # m4 không có bản ghi
RECORDS = {
    "m1": {"gemini_reads": [OKG, OKG], "gemini_direct_verdict": {"dung": True}, "seconds": 3.0, "api_calls": 2},
    "m2": {"gemini_reads": [WRONGPOS, WRONGPOS], "gemini_direct_verdict": {"dung": False, "loi": ["sai_mach_cacbon"]}, "seconds": 4.0, "api_calls": 2},
    "m3": {"gemini_reads": [BADG, OKG], "gemini_direct_verdict": {"dung": True}, "seconds": 5.0, "api_calls": 2},
}


class AblationTests(unittest.TestCase):
    def test_bon_phuong_an_cho_ket_qua_khac_nhau_dung_nhu_thiet_ke(self):
        res = ab.run_all(CASES, RECORDS)
        pred = lambda b, i: res[b][0][i]["du_doan"]
        self.assertEqual(pred("A", 1), "sai_mach_cacbon")                       # Gemini tự nhận xét nhãn khác đáp án
        self.assertEqual(pred("B", 1), "sai_yeu_cau_de")                        # B chỉ biết "không trùng đề"
        self.assertEqual(pred("C", 1), "sai_vi_tri_nhom_chuc")                  # C phân loại đúng
        self.assertEqual(res["C"][0][2]["du_doan"], "sai_hoa_tri")              # m3: đọc lần 1 sai hóa trị
        self.assertEqual(res["C2"][0][2]["ket_qua"], ev_NO)                     # C2: hai lần đọc bất đồng nên từ chối
        self.assertEqual(res["C2"][1]["khong_du_can_cu"], 2)                    # m3 (bất đồng) và m4 (không có bản ghi)
        for b in ab.BASELINES:
            self.assertEqual(res[b][0][3]["ket_qua"], ev_NO)                    # thiếu bản ghi: không tự tạo kết quả

    def test_bang_rong_khong_bia_so(self):
        md = ab.format_markdown({})
        self.assertEqual(md.count("chưa có dữ liệu"), 4)
        self.assertNotRegex(md, r"\d\.\d{3}")

    def test_doc_anh(self):
        rows, sm = ab.recognition_report(CASES, RECORDS)
        self.assertEqual(sm["so_mau"], 3)
        self.assertEqual(sm["duoc_ket_luan"], 3)
        self.assertAlmostEqual(sm["khop_do_thi_tuyet_doi"], 2 / 3)               # m3: đồ thị đọc lần 1 sai hóa trị so với chuẩn
        self.assertIsNotNone(sm["khoang_tin_cay_wilson"])

    def test_chi_phi(self):
        c = ab.cost_report(RECORDS)
        self.assertAlmostEqual(c["giay_tb"], 4.0)
        self.assertEqual(c["so_lan_goi_api_tb"], 2.0)

    def test_phuong_an_d_tu_nhat_ky(self):
        att = [{"result": "tu_sua_dung", "errors": ["sai_hoa_tri"], "hints": 0, "n_fixes": 1}, {"result": "sua_dung_sau_goi_y", "errors": ["sai_mach_cacbon"], "hints": 2, "n_fixes": 1},
               {"result": "xem_dap_an", "errors": ["sai_mach_cacbon"], "hints": 3, "n_fixes": 2}, {"result": "tu_sua_dung", "errors": [], "hints": 0, "n_fixes": 0}]
        s = ab.summarize_sessions(att)
        self.assertEqual(s["so_luot"], 4)
        self.assertAlmostEqual(s["ti_le_tu_sua_duoc_loi"], 2 / 3)
        self.assertEqual(ab.summarize_sessions([]), {"so_luot": 0})


ev_NO = "khong_du_can_cu"

if __name__ == "__main__":
    unittest.main()
