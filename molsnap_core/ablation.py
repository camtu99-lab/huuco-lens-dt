"""Đối chứng các phương án A, B, C, C2 và tóm tắt phương án D từ nhật ký học tập.

A   Gemini độc lập: dùng nhận xét đúng/sai và nhãn lỗi do Gemini tự đưa ra khi xem ảnh.
B   Gemini + kiểm chứng: đồ thị Gemini đọc -> kiểm tra hóa trị và so cấu trúc với đề (không phân loại lỗi chi tiết).
C   B + bộ quy tắc chẩn đoán lỗi (ErrorLab) trên một lần đọc.
C2  C + nhiều lần đọc đối chứng, quy kết nguồn lỗi và từ chối kết luận khi bất đồng (MolSnap-CVR).
D   MolSnap đầy đủ có học sinh xác nhận và gợi ý sửa lỗi: đo trên nhật ký học tập thật (summarize_sessions), không mô phỏng.

Đầu vào là KẾT QUẢ ĐÃ GHI LẠI của Gemini cho từng mẫu (recorded outputs), nên chạy lại được nhiều lần, không tốn lượt và không đổi kết quả.
Mã này không chứa dữ liệu hay kết quả nào; chưa có dữ liệu thì bảng kết quả để trống.
"""
from . import evidence as ev
from .parse import from_ai_graph, from_smiles, ParseError
from .graph import canonical
from .diagnose import diagnose
from .cvr import verify_and_diagnose, candidates_from

BASELINES = {"A": "Gemini độc lập", "B": "Gemini + kiểm tra hóa trị và so cấu trúc", "C": "B + bộ quy tắc chẩn đoán lỗi",
             "C2": "C + đối chứng nhiều lần đọc và từ chối kết luận"}


def _first_graph(rec):
    reads = rec.get("gemini_reads") or []
    if not reads:
        return None
    try:
        return from_ai_graph(reads[0])[0]
    except ParseError:
        return None


def predict_A(rec, target):
    v = rec.get("gemini_direct_verdict")
    if not isinstance(v, dict) or "dung" not in v:
        return None
    return {"trang_thai": "dung" if v["dung"] else "sai", "loi": [{"ma": m} for m in (v.get("loi") or [])] if not v["dung"] else []}


def predict_B(rec, target):
    g = _first_graph(rec)
    if g is None:
        return None
    if g.valence_issues():
        return {"trang_thai": "sai", "loi": [{"ma": "sai_hoa_tri"}]}
    return {"trang_thai": "dung", "loi": []} if canonical(g) == canonical(target) else {"trang_thai": "sai", "loi": [{"ma": "sai_yeu_cau_de"}]}


def predict_C(rec, target):
    g = _first_graph(rec)
    return None if g is None else diagnose(g, target, confirmed=True)


def predict_C2(rec, target):
    cands, _, _ = candidates_from(rec.get("gemini_reads") or [], rec.get("gemini_direct_smiles") or [])
    return verify_and_diagnose(cands, target, confirmed=False)


PREDICTORS = {"A": predict_A, "B": predict_B, "C": predict_C, "C2": predict_C2}


def run_all(cases, records, which=("A", "B", "C", "C2")):
    """cases: các dòng bộ dữ liệu (id, dap_an_smiles hoặc ct_dap_an, dap_an_loi: list). records: dict mã mẫu -> kết quả Gemini ghi lại.
    Trả về {phương án: (các dòng, tóm tắt)}. Mẫu thiếu bản ghi tính là 'không đủ căn cứ'."""
    out = {}
    for b in which:
        def pred(c, b=b):
            rec = records.get(c["id"])
            if rec is None:
                return None
            return PREDICTORS[b](rec, from_smiles(c["dap_an_smiles"]))
        rows, sm = ev.run_diagnosis_benchmark(cases, pred)
        out[b] = (rows, sm)
    return out


def recognition_report(cases, records):
    """Độ chính xác đọc ảnh: khớp đồ thị tuyệt đối và P/R/F1 mức nguyên tử, liên kết (xấp xỉ theo đa tập) so với đồ thị chuẩn do chuyên gia xác nhận."""
    rows = []
    for c in cases:
        gold_smiles = c.get("do_thi_chuan_smiles")
        rec = records.get(c["id"])
        if not gold_smiles:
            continue
        g = _first_graph(rec) if rec else None
        row = ev.recognition_row(c["id"], from_smiles(gold_smiles), g, (rec or {}).get("seconds", 0.0), c.get("dieu_kien", ""))
        if g is not None:
            m = ev.graph_multiset_prf(from_smiles(gold_smiles), g)
            row.update({"f1_nguyen_tu": m["nguyen_tu"]["f1"], "f1_lien_ket": m["lien_ket"]["f1"]})
        rows.append(row)
    ans = [r for r in rows if r["ket_qua"] != ev.NO_BASIS]
    return rows, {"so_mau": len(rows), "duoc_ket_luan": len(ans), "khop_do_thi_tuyet_doi": ev.safe_div(sum(1 for r in ans if r["ket_qua"] == "dung"), len(ans)),
                  "khoang_tin_cay_wilson": ev.wilson_ci(sum(1 for r in ans if r["ket_qua"] == "dung"), len(ans))}


def cost_report(records):
    """Thời gian và số lần gọi API ghi trong bản ghi (nếu có)."""
    n = len(records)
    secs = [r.get("seconds") for r in records.values() if isinstance(r.get("seconds"), (int, float))]
    calls = [r.get("api_calls") for r in records.values() if isinstance(r.get("api_calls"), (int, float))]
    return {"so_mau": n, "giay_tb": ev.safe_div(sum(secs), len(secs)), "so_lan_goi_api_tb": ev.safe_div(sum(calls), len(calls))}


def summarize_sessions(attempts):
    """Phương án D: tỉ lệ học sinh tự sửa đúng từ nhật ký lượt luyện tập (dòng của Store.attempts_of hoặc CSV đã xuất)."""
    n = len(attempts)
    if not n:
        return {"so_luot": 0}
    cnt = lambda r: sum(1 for a in attempts if a["result"] == r)
    solved = cnt("tu_sua_dung") + cnt("sua_dung_sau_goi_y")
    had_error = [a for a in attempts if a["errors"]]
    fixed = [a for a in had_error if a["result"] in ("tu_sua_dung", "sua_dung_sau_goi_y")]
    return {"so_luot": n, "ti_le_tu_lam_dung_khong_goi_y": cnt("tu_sua_dung") / n, "ti_le_dung_sau_goi_y": cnt("sua_dung_sau_goi_y") / n,
            "ti_le_xem_dap_an": cnt("xem_dap_an") / n, "ti_le_chua_xong": cnt("chua_xong") / n, "ti_le_dung_chung": solved / n,
            "so_luot_co_loi": len(had_error), "ti_le_tu_sua_duoc_loi": ev.safe_div(len(fixed), len(had_error)),
            "goi_y_tb": sum(a.get("hints", 0) for a in attempts) / n, "lan_sua_tb": sum(a.get("n_fixes", 0) for a in attempts) / n}


def format_markdown(results, recog=None, cost=None, sessions=None):
    """Bảng Markdown để dán vào báo cáo. Ô không có dữ liệu ghi 'chưa có dữ liệu'; không điền số thay thế."""
    f = lambda x: "chưa có dữ liệu" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x))
    L = ["| Phương án | Số ca | Độ phủ | Khớp tuyệt đối | Macro-F1 | Phát hiện lỗi F1 | Từ chối |", "|---|---|---|---|---|---|---|"]
    for b in BASELINES:
        if b in results:
            sm = results[b][1]
            det = sm.get("phat_hien_co_loi") or {}
            L.append(f"| {b}. {BASELINES[b]} | {sm['so_ca']} | {f(sm['do_phu'])} | {f(sm['khop_tuyet_doi'])} | {f(sm['macro_f1'])} | {f(det.get('f1'))} | {sm['khong_du_can_cu']} |")
        else:
            L.append(f"| {b}. {BASELINES[b]} | chưa có dữ liệu | | | | | |")
    if recog:
        L += ["", f"Đọc ảnh: khớp đồ thị tuyệt đối {f(recog['khop_do_thi_tuyet_doi'])} (khoảng tin cậy Wilson 95%: {f(recog['khoang_tin_cay_wilson'])}), n = {recog['duoc_ket_luan']}."]
    if sessions:
        L += ["", "Phương án D (nhật ký học tập): " + ", ".join(f"{k} = {f(v)}" for k, v in sessions.items())]
    return "\n".join(L)
