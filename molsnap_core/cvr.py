"""MolSnap-CVR (Chemical Structure Verification & Repair): nhận dạng có đối chứng và quy kết nguồn lỗi.

Quy trình: nhiều lần đọc ảnh -> đồ thị ứng viên -> đồng thuận -> kiểm chứng độc lập -> quy kết nguồn lỗi -> từ chối kết luận khi chưa đủ căn cứ.

Ba giả thuyết về nguồn của một cấu trúc có vẻ sai:
  nhan_dang_ai  máy đọc sai nét vẽ (hình học sinh có thể đúng)
  hoc_sinh      máy đọc đúng, bài làm của học sinh sai hoặc không đáp ứng đề
  chua_ro       chưa đủ căn cứ để chọn: hệ thống yêu cầu học sinh xác nhận

Các ngưỡng ở đây là QUY TẮC MINH BẠCH, CHƯA HIỆU CHUẨN. MolSnap không hiển thị phần trăm tin cậy cho đến khi có dữ liệu hiệu chuẩn
(xem calibration.py). Độ tự tin do Gemini tự khai không được dùng làm bằng chứng.
"""
from collections import Counter
from .graph import canonical
from .parse import from_ai_graph, from_smiles, ParseError
from .diagnose import diagnose, _err

FEATURES = ["bat_dong_cau_truc", "bat_dong_lien_ket", "bat_dong_nguyen_tu", "phat_hoa_tri", "bat_dong_cong_thuc", "khong_lien_thong"]


def _multiset_atoms(g):
    return Counter((a.el, g.total_h(i)) for i, a in g.atoms.items())


def _multiset_bonds(g):
    c = Counter()
    for b, o in g.bonds.items():
        i, j = tuple(b)
        c[(tuple(sorted((g.atoms[i].el, g.atoms[j].el))), o)] += 1
    return c


def jaccard(a, b):
    """Jaccard trên đa tập. Hai đa tập cùng rỗng coi là giống nhau (1.0)."""
    inter, union = sum((a & b).values()), sum((a | b).values())
    return 1.0 if union == 0 else inter / union


def is_valid(g):
    return bool(g.atoms) and g.is_connected() and not g.valence_issues()


def consensus(cands):
    """cands: danh sách MolGraph (có thể có None khi một lần đọc thất bại). Trả về thông tin đồng thuận và vector bất đồng."""
    ok = [c for c in cands if c is not None and c.atoms]
    k = len(ok)
    out = {"k": k, "k_that_bai": len(cands) - k, "graph": None, "dong_thuan": 0.0, "vector": None, "hop_le": [], "ct": []}
    if k == 0:
        return out
    keys = [canonical(c) for c in ok]
    mode_key, mode_n = Counter(keys).most_common(1)[0]
    mode_g = ok[keys.index(mode_key)]
    ab, bb = _multiset_atoms(mode_g), _multiset_bonds(mode_g)
    aj = sum(jaccard(ab, _multiset_atoms(c)) for c in ok) / k
    bj = sum(jaccard(bb, _multiset_bonds(c)) for c in ok) / k
    forms = [tuple(sorted(c.formula().items())) for c in ok]
    out.update({
        "graph": mode_g, "dong_thuan": mode_n / k, "hop_le": [is_valid(c) for c in ok], "ct": [c.hill() for c in ok],
        "vector": {"bat_dong_cau_truc": 1 - mode_n / k, "bat_dong_lien_ket": 1 - bj, "bat_dong_nguyen_tu": 1 - aj,
                   "phat_hoa_tri": sum(1 for c in ok if c.valence_issues()) / k,
                   "bat_dong_cong_thuc": 1 - Counter(forms).most_common(1)[0][1] / k,
                   "khong_lien_thong": sum(1 for c in ok if not c.is_connected()) / k}})
    return out


def _issue_signature(g):
    return Counter((v["el"], v["loai"]) for v in g.valence_issues())


def attribute_source(cands, confirmed=False):
    """Quy kết nguồn lỗi theo quy tắc minh bạch. confirmed: học sinh đã xác nhận hình tái dựng khớp bài vẽ của mình."""
    cons = consensus(cands)
    res = {"nguon": "chua_ro", "can_xac_nhan": True, "graph": cons["graph"], "ly_do": "", "dong_thuan": cons["dong_thuan"], "k": cons["k"], "vector": cons["vector"]}
    if cons["k"] == 0:
        res["ly_do"] = "Không đọc được cấu trúc nào từ ảnh."
        return res
    g = cons["graph"]
    if confirmed:
        res.update(nguon="hoc_sinh", can_xac_nhan=False,
                   ly_do="Học sinh đã xác nhận hình tái dựng đúng với bài vẽ, nên cấu trúc này được coi là bài làm của học sinh.")
        return res
    if cons["k"] < 2:
        res["ly_do"] = "Mới có một lần đọc ảnh nên chưa thể phân biệt lỗi do máy đọc nhầm hay do bài vẽ. Hãy kiểm tra hình tái dựng rồi xác nhận."
        return res
    valid = cons["hop_le"]
    if cons["dong_thuan"] == 1.0:
        res.update(nguon="hoc_sinh" if not valid[0] else "hop_le", can_xac_nhan=False,
                   ly_do="Các lần đọc ảnh cho cùng một cấu trúc nên kết quả đọc ổn định.")
        return res
    # các lần đọc không thống nhất
    if any(valid) and not all(valid):
        res["nguon"] = "nhan_dang_ai"
        res["ly_do"] = "Các lần đọc ảnh cho kết quả khác nhau và có lần đọc ra cấu trúc hợp lệ: nhiều khả năng máy đọc nhầm một nét vẽ."
        return res
    if all(valid):
        res["ly_do"] = "Các lần đọc ảnh khác nhau nhưng đều là cấu trúc hợp lệ: chưa biết hình nào đúng với bài vẽ."
        return res
    sigs = [_issue_signature(c) for c in cands if c is not None and c.atoms]
    if all(s == sigs[0] for s in sigs):
        res.update(nguon="hoc_sinh", can_xac_nhan=True,
                   ly_do="Dù chi tiết đọc có khác nhau, mọi lần đọc đều cho cùng loại lỗi hóa trị: nhiều khả năng đây là lỗi trong bài vẽ. Em hãy xác nhận hình tái dựng.")
        return res
    res["ly_do"] = "Các lần đọc ảnh khác nhau và đều có lỗi nhưng không cùng loại lỗi: chưa đủ căn cứ để kết luận."
    return res


def candidates_from(graph_dicts, smiles_list=()):
    """Dựng danh sách ứng viên từ nhiều lần đọc đồ thị và (tùy chọn) các lần đọc SMILES độc lập. Trả về (ứng viên, cảnh báo, số lần thất bại)."""
    cands, warns, fails = [], [], 0
    for d in graph_dicts or []:
        try:
            g, w = from_ai_graph(d)
            cands.append(g)
            warns.extend(w)
        except ParseError:
            cands.append(None)
            fails += 1
    for s in smiles_list or []:
        try:
            cands.append(from_smiles(s))
        except ParseError:
            fails += 1
    return cands, sorted(set(warns)), fails


def verify_and_diagnose(cands, target=None, confirmed=False, warnings=()):
    """Toàn bộ quy trình kiểm chứng. Không tự chọn kết quả khi các nguồn bất đồng: trả về 'khong_du_thong_tin' kèm yêu cầu xác nhận.

    Kết quả của ErrorLab được bổ sung các trường: nguon (hoc_sinh/nhan_dang_ai/chua_ro/hop_le), can_xac_nhan, dong_thuan, ly_do_nguon.
    """
    att = attribute_source(cands, confirmed)
    g = att["graph"]
    if g is None or att["nguon"] in ("chua_ro", "nhan_dang_ai") or (att["can_xac_nhan"] and not confirmed):
        res = {"trang_thai": "khong_du_thong_tin", "loi": [_err("khong_du_thong_tin", cause=att["ly_do"] or "Chưa đủ căn cứ để kết luận.", verified=False)],
               "loi_chinh": "khong_du_thong_tin", "ct_hoc_sinh": g.hill() if g else "", "ct_dap_an": target.hill() if target else "", "da_xac_nhan": bool(confirmed)}
    elif target is None:
        # chỉ kiểm tra tính hợp lệ của hình, không có đề bài để so
        issues = g.valence_issues()
        res = {"trang_thai": "sai" if issues or not g.is_connected() else "hop_le", "loi": [], "loi_chinh": None, "ct_hoc_sinh": g.hill(),
               "ct_dap_an": "", "da_xac_nhan": bool(confirmed)}
        from .diagnose import diagnose as _d
        probe = _d(g, g, confirmed=confirmed, warnings=warnings)   # dùng chính cấu trúc làm "đề": chỉ lỗi hóa trị và tính liên thông còn lại
        res["loi"], res["loi_chinh"] = probe["loi"], probe["loi_chinh"]
        if probe["trang_thai"] == "khong_du_thong_tin":
            res["trang_thai"] = "khong_du_thong_tin"
        elif probe["trang_thai"] == "dung":
            res["trang_thai"] = "hop_le"
    else:
        res = diagnose(g, target, confirmed=confirmed or att["nguon"] == "hop_le" or att["dong_thuan"] == 1.0, warnings=warnings)
    # ba tình huống của bước chẩn đoán: máy đọc sai / học sinh vẽ không hợp lệ / hợp lệ nhưng không đáp ứng đề
    if res["trang_thai"] == "khong_du_thong_tin":
        res["tinh_huong"] = "ai_doc_sai_co_the" if att["nguon"] == "nhan_dang_ai" else "chua_ro"
    elif res["trang_thai"] in ("dung", "hop_le"):
        res["tinh_huong"] = "dung"
    elif any(e["ma"] == "sai_hoa_tri" for e in res["loi"]):
        res["tinh_huong"] = "hoc_sinh_khong_hop_le"
    else:
        res["tinh_huong"] = "hop_le_sai_yeu_cau"
    res["nguon"], res["can_xac_nhan"] = att["nguon"], att["can_xac_nhan"]
    res["dong_thuan"], res["ly_do_nguon"], res["so_lan_doc"] = att["dong_thuan"], att["ly_do"], att["k"]
    return res
