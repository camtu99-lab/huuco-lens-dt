"""Chạy đối chứng các phương án A, B, C, C2 từ bộ dữ liệu và kết quả Gemini đã ghi lại.

Dùng:  python evaluation/run_ablation.py --cases duong_dan/bo_du_lieu.csv --records duong_dan/gemini_da_ghi.json --out ket_qua
Không có tệp thì in bảng trống (ô ghi 'chưa có dữ liệu'). Mã không sinh số liệu nào.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from molsnap_core import ablation as ab, evidence as ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases"), ap.add_argument("--records"), ap.add_argument("--sessions", help="CSV xuất từ Store.export_csv cho phương án D"), ap.add_argument("--out", default="ket_qua_danh_gia")
    a = ap.parse_args()
    results, recog, cost, sessions = {}, None, None, None
    if a.cases and a.records:
        with open(a.cases, encoding="utf-8-sig") as f:
            cases = ev.load_cases_csv(f.read())
        for c in cases:
            c["id"] = c.get("ma_mau") or c.get("ma_ca") or c.get("id")
            c["dap_an_loi"] = [x.strip() for x in (c.get("nhan_loi_chot") or c.get("dap_an_loi") or "").split(";") if x.strip()]
        with open(a.records, encoding="utf-8") as f:
            records = json.load(f)
        results = ab.run_all(cases, records)
        recog = ab.recognition_report(cases, records)[1]
        cost = ab.cost_report(records)
    if a.sessions:
        import csv
        with open(a.sessions, encoding="utf-8-sig") as f:
            rows = [{"result": r["ket_qua"], "errors": json.loads(r["cac_loi"] or "[]"), "hints": int(r["so_goi_y"]), "n_fixes": int(r["so_lan_sua"])} for r in csv.DictReader(f)]
        sessions = ab.summarize_sessions(rows)
    md = ab.format_markdown(results, recog, cost, sessions)
    os.makedirs(a.out, exist_ok=True)
    meta = ev.run_metadata({"cases": a.cases, "records": a.records, "sessions": a.sessions})
    with open(os.path.join(a.out, "bang_ket_qua.md"), "w", encoding="utf-8") as f:
        f.write(md + "\n\n<!-- " + json.dumps(meta, ensure_ascii=False) + " -->\n")
    for b, (rows, _) in results.items():
        with open(os.path.join(a.out, f"chi_tiet_{b}.csv"), "w", encoding="utf-8-sig", newline="") as f:
            f.write(ev.to_csv(rows, meta))
    print(md)


if __name__ == "__main__":
    main()
