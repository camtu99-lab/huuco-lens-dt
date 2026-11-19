"""MolSnap Evidence: đánh giá có thể tái lập.

Quy ước trung thực:
  - Không tạo số liệu: mọi chỉ số tính từ bộ ca kiểm thử do người dùng cung cấp, đáp án chuẩn do con người xác minh.
  - Đáp án chuẩn không được lấy từ kết quả tự sinh của MolSnap.
  - Ca máy trả "không đủ căn cứ" được đếm riêng (độ phủ), không tính là đúng cũng không tính là sai.
"""
import csv
import io
import json
import platform
import time
from . import __version__

NO_BASIS = "khong_du_can_cu"


def safe_div(a, b):
    return a / b if b else None


def binary_prf(y_true, y_pred):
    """Precision, Recall, F1 cho lớp dương (True). Trả None khi mẫu số bằng 0 (không bịa số 0)."""
    tp = sum(1 for t, p in zip(y_true, y_pred) if t and p)
    fp = sum(1 for t, p in zip(y_true, y_pred) if not t and p)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t and not p)
    tn = sum(1 for t, p in zip(y_true, y_pred) if not t and not p)
    pr, rc = safe_div(tp, tp + fp), safe_div(tp, tp + fn)
    f1 = safe_div(2 * pr * rc, pr + rc) if pr is not None and rc is not None else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": pr, "recall": rc, "f1": f1,
            "accuracy": safe_div(tp + tn, tp + fp + fn + tn)}


def multilabel_prf(true_sets, pred_sets, labels):
    """P/R/F1 theo từng nhãn lỗi, kèm macro-F1 (trung bình các nhãn có F1) và tỉ lệ khớp tuyệt đối."""
    per = {l: binary_prf([l in t for t in true_sets], [l in p for p in pred_sets]) for l in labels}
    f1s = [v["f1"] for v in per.values() if v["f1"] is not None]
    return {"theo_nhan": per, "macro_f1": safe_div(sum(f1s), len(f1s)),
            "khop_tuyet_doi": safe_div(sum(1 for t, p in zip(true_sets, pred_sets) if set(t) == set(p)), len(true_sets))}


def run_metadata(config=None):
    meta = {"thoi_gian": time.strftime("%Y-%m-%d %H:%M:%S"), "molsnap_core": __version__, "python": platform.python_version(),
            "he_dieu_hanh": platform.platform(), "cau_hinh": config or {}}
    try:
        import rdkit
        meta["rdkit"] = rdkit.__version__
    except Exception:
        meta["rdkit"] = None
    return meta


# ------------------------------------------------------------------ đánh giá chẩn đoán lỗi
def run_diagnosis_benchmark(cases, predictor):
    """cases: [{id, nhom, dap_an_loi: [mã lỗi] (rỗng nếu bài đúng), ...}]; predictor(case) -> dict kết quả của ErrorLab
    ({"trang_thai", "loi": [{"ma"}]}) hoặc None nếu máy không xử lý được.
    Trả về (các dòng kết quả, tóm tắt)."""
    rows = []
    for c in cases:
        t0 = time.time()
        try:
            r = predictor(c)
        except Exception as e:
            r = None
            err = type(e).__name__
        else:
            err = ""
        dt = round(time.time() - t0, 4)
        gold = sorted(set(c.get("dap_an_loi") or []))
        if r is None or r["trang_thai"] == "khong_du_thong_tin":
            rows.append({"ma_ca": c["id"], "nhom": c.get("nhom", ""), "dap_an": ";".join(gold), "du_doan": "", "ket_qua": NO_BASIS, "giay": dt, "loi_he_thong": err})
            continue
        pred = sorted({e["ma"] for e in r["loi"]}) if r["trang_thai"] == "sai" else []
        rows.append({"ma_ca": c["id"], "nhom": c.get("nhom", ""), "dap_an": ";".join(gold), "du_doan": ";".join(pred),
                     "ket_qua": "dung" if pred == gold else "sai", "giay": dt, "loi_he_thong": ""})
    return rows, summarize_diagnosis(rows)


def summarize_diagnosis(rows):
    answered = [r for r in rows if r["ket_qua"] != NO_BASIS]
    labels = sorted({l for r in rows for l in (r["dap_an"].split(";") + r["du_doan"].split(";")) if l})
    ts = [set(filter(None, r["dap_an"].split(";"))) for r in answered]
    ps = [set(filter(None, r["du_doan"].split(";"))) for r in answered]
    ml = multilabel_prf(ts, ps, labels) if answered else None
    has_err_t = [bool(t) for t in ts]
    has_err_p = [bool(p) for p in ps]
    return {"so_ca": len(rows), "so_ca_duoc_ket_luan": len(answered), "khong_du_can_cu": len(rows) - len(answered),
            "do_phu": safe_div(len(answered), len(rows)), "khop_tuyet_doi": ml["khop_tuyet_doi"] if ml else None,
            "macro_f1": ml["macro_f1"] if ml else None, "theo_nhan": ml["theo_nhan"] if ml else {},
            "phat_hien_co_loi": binary_prf(has_err_t, has_err_p) if answered else None,
            "giay_trung_binh": safe_div(sum(r["giay"] for r in rows), len(rows))}


# ------------------------------------------------------------------ đánh giá đếm đồng phân
def run_isomer_benchmark(cases, counter):
    """cases: [{id, cong_thuc, dap_an_so}]; counter(cong_thuc) -> số đồng phân (int) hoặc None nếu vượt phạm vi/thời gian."""
    rows = []
    for c in cases:
        t0 = time.time()
        try:
            n = counter(c["cong_thuc"])
            err = ""
        except Exception as e:
            n, err = None, type(e).__name__
        dt = round(time.time() - t0, 3)
        gold = int(c["dap_an_so"])
        if n is None:
            kq = NO_BASIS
        else:
            kq = "dung" if n == gold else "sai"
        rows.append({"ma_ca": c["id"], "cong_thuc": c["cong_thuc"], "dap_an_so": gold, "may_dem": "" if n is None else n, "ket_qua": kq,
                     "sai_lech": "" if n is None else n - gold, "giay": dt, "loi_he_thong": err})
    ans = [r for r in rows if r["ket_qua"] != NO_BASIS]
    return rows, {"so_ca": len(rows), "so_ca_duoc_ket_luan": len(ans), "khong_du_can_cu": len(rows) - len(ans),
                  "do_chinh_xac": safe_div(sum(1 for r in ans if r["ket_qua"] == "dung"), len(ans)),
                  "sai_lech_tuyet_doi_tb": safe_div(sum(abs(r["sai_lech"]) for r in ans), len(ans)),
                  "giay_trung_binh": safe_div(sum(r["giay"] for r in rows), len(rows))}


# ------------------------------------------------------------------ nhận dạng ảnh
def recognition_row(case_id, gold_graph, pred_graph, seconds=0.0, group=""):
    """So đồ thị máy chép từ ảnh với đồ thị chuẩn (do người vẽ lại từ ảnh, không phải từ kết quả của MolSnap)."""
    from .graph import canonical
    if pred_graph is None:
        return {"ma_ca": case_id, "nhom": group, "ket_qua": NO_BASIS, "khop_cong_thuc": "", "khop_cau_tao": "", "giay": seconds}
    same_f = gold_graph.formula() == pred_graph.formula()
    same_s = canonical(gold_graph) == canonical(pred_graph)
    return {"ma_ca": case_id, "nhom": group, "ket_qua": "dung" if same_s else "sai", "khop_cong_thuc": same_f, "khop_cau_tao": same_s, "giay": seconds}


def to_csv(rows, meta=None):
    """CSV có dòng đầu ghi phiên bản và cấu hình thử nghiệm để tái lập."""
    buf = io.StringIO()
    if meta:
        buf.write("# " + json.dumps(meta, ensure_ascii=False) + "\n")
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue()


def load_cases_csv(text):
    lines = [l for l in text.splitlines() if not l.startswith("#")]
    return list(csv.DictReader(io.StringIO("\n".join(lines))))


# ------------------------------------------------------------------ độ tin cậy của chính phép đánh giá
def cohen_kappa(a, b):
    """Hệ số đồng thuận Cohen giữa hai người gán nhãn độc lập (danh sách nhãn cùng độ dài). None nếu không tính được."""
    if len(a) != len(b) or not a:
        return None
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    labels = set(a) | set(b)
    pe = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    return None if pe == 1 else (po - pe) / (1 - pe)


def wilson_ci(k, n, z=1.96):
    """Khoảng tin cậy Wilson 95% cho một tỉ lệ (k đúng trên n). Phù hợp khi mẫu nhỏ."""
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def bootstrap_ci(values, stat=None, n_boot=2000, seed=0, alpha=0.05):
    """Khoảng tin cậy bootstrap (phân vị) cho thống kê của một danh sách số; mặc định là trung bình."""
    import random
    if not values:
        return None
    stat = stat or (lambda v: sum(v) / len(v))
    rnd = random.Random(seed)
    xs = sorted(stat([rnd.choice(values) for _ in values]) for _ in range(n_boot))
    return xs[int(n_boot * alpha / 2)], xs[int(n_boot * (1 - alpha / 2)) - 1]


def graph_multiset_prf(gold, pred):
    """Precision, Recall, F1 mức nguyên tử và mức liên kết giữa đồ thị chuẩn và đồ thị máy đọc.
    So khớp theo đa tập (nguyên tố + số H) và (cặp nguyên tố + bậc liên kết), KHÔNG xét vị trí không gian: là xấp xỉ, thấp hơn đo bằng ghép đồ thị tối ưu."""
    from .cvr import _multiset_atoms, _multiset_bonds

    def prf(g, p):
        inter = sum((g & p).values())
        pr, rc = safe_div(inter, sum(p.values())), safe_div(inter, sum(g.values()))
        return {"precision": pr, "recall": rc, "f1": safe_div(2 * pr * rc, pr + rc) if pr is not None and rc is not None else None}
    return {"nguyen_tu": prf(_multiset_atoms(gold), _multiset_atoms(pred)), "lien_ket": prf(_multiset_bonds(gold), _multiset_bonds(pred))}
