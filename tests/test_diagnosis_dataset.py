"""Chạy ErrorLab trên bộ ca tổng hợp có đáp án do người soạn gán tay (benchmarks/loi_cau_truc_tong_hop.csv).

LƯU Ý TRUNG THỰC: đây là kiểm thử quy tắc (hồi quy) trên bài làm GÕ TAY do người soạn tạo, KHÔNG phải đánh giá trên bài làm thật của học sinh
và KHÔNG đo độ chính xác nhận dạng ảnh. Không được trích kết quả này như độ chính xác của MolSnap ngoài thực tế."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from molsnap_core.parse import from_condensed, from_smiles
from molsnap_core.diagnose import diagnose, ERR_NAMES
from molsnap_core.evidence import run_diagnosis_benchmark, load_cases_csv


def _cases():
    with open(os.path.join(ROOT, "benchmarks", "loi_cau_truc_tong_hop.csv"), encoding="utf-8") as f:
        cs = load_cases_csv(f.read())
    for c in cs:
        c["id"] = c["ma_ca"]
        c["dap_an_loi"] = [x for x in c["dap_an_loi"].split(";") if x]
    return cs


class DiagnosisDataset(unittest.TestCase):
    def test_moi_ca_khop_dap_an_gan_tay(self):
        rows, summary = run_diagnosis_benchmark(_cases(), lambda c: diagnose(from_condensed(c["bai_lam_thu_gon"]), from_smiles(c["dap_an_smiles"])))
        bad = [(r["ma_ca"], r["dap_an"], r["du_doan"]) for r in rows if r["ket_qua"] != "dung"]
        self.assertEqual(bad, [])
        self.assertEqual(summary["khong_du_can_cu"], 0)

    def test_phu_du_cac_loai_loi(self):
        codes = {m for c in _cases() for m in c["dap_an_loi"]}
        self.assertTrue(codes >= {"sai_hoa_tri", "thieu_thua_nguyen_tu", "sai_bac_lien_ket", "sai_cong_thuc", "sai_mach_cacbon", "nham_dong_phan", "sai_vi_tri_nhom_chuc"})
        self.assertTrue(codes <= set(ERR_NAMES))

    def test_nhan_hop_le_khong_bi_bao_loi(self):
        for c in _cases():
            if not c["dap_an_loi"]:
                r = diagnose(from_condensed(c["bai_lam_thu_gon"]), from_smiles(c["dap_an_smiles"]))
                self.assertEqual(r["trang_thai"], "dung", c["ma_ca"])


if __name__ == "__main__":
    unittest.main()
