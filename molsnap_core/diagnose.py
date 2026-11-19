"""ErrorLab: phát hiện, phân loại và định vị lỗi cấu trúc của học sinh.

Mọi kết luận đều tính bằng thuật toán trên đồ thị phân tử. AI chỉ dùng để chép ảnh thành đồ thị, không dùng để chấm.
"""
from collections import Counter
from .graph import MolGraph, canonical, canonical_map, carbon_chain, VALENCES

ERR_NAMES = {
    "khong_du_thong_tin": "Chưa đủ thông tin để kết luận",
    "sai_hoa_tri": "Sai hóa trị",
    "thieu_thua_nguyen_tu": "Thiếu hoặc thừa nguyên tử",
    "sai_bac_lien_ket": "Sai bậc liên kết",
    "sai_cong_thuc": "Sai công thức phân tử",
    "sai_mach_cacbon": "Sai mạch cacbon",
    "nham_dong_phan": "Nhầm đồng phân cấu tạo (khác nhóm chức)",
    "sai_vi_tri_nhom_chuc": "Sai vị trí nhóm chức hoặc liên kết bội",
    "sai_yeu_cau_de": "Chưa đúng cấu trúc đề bài yêu cầu",
}
PRIORITY = list(ERR_NAMES)
RULES = {
    "khong_du_thong_tin": "Chỉ kết luận khi hình nối liền thành một phân tử và nhận dạng đã được xác nhận.",
    "sai_hoa_tri": "Hóa trị: C = 4, N = 3, O = 2, H và halogen = 1 (tổng số liên kết quanh nguyên tử, tính cả liên kết tới H).",
    "thieu_thua_nguyen_tu": "Số nguyên tử mỗi nguyên tố (C, O, N, halogen) phải bằng số trong công thức phân tử của chất cần viết.",
    "sai_bac_lien_ket": "Hai cấu trúc có cùng khung nguyên tử nhưng khác bậc liên kết: mỗi liên kết bội làm giảm 2 nguyên tử H.",
    "sai_cong_thuc": "Công thức phân tử đúng phải có đúng số nguyên tử H của chất cần viết.",
    "sai_mach_cacbon": "Đồng phân mạch cacbon có cùng công thức nhưng khác cách sắp xếp (thẳng hay phân nhánh) các nguyên tử C.",
    "nham_dong_phan": "Đồng phân nhóm chức có cùng công thức phân tử nhưng khác loại nhóm chức.",
    "sai_vi_tri_nhom_chuc": "Đồng phân vị trí có cùng mạch cacbon và cùng loại nhóm chức nhưng nhóm chức hoặc liên kết bội gắn ở cacbon khác.",
    "sai_yeu_cau_de": "Cấu trúc hợp lệ nhưng không trùng với chất đề bài yêu cầu.",
}


# ------------------------------------------------------------------ nhóm chức (thuần đồ thị)
def _o_double(g, c):
    return [j for j, o in g.neighbors(c) if o == 2 and g.atoms[j].el == "O"]


def benzene_rings(g):
    """Các vòng 6 nguyên tử C có ba nối đôi xen kẽ (vòng benzen)."""
    cs = [i for i, a in g.atoms.items() if a.el == "C"]
    adj = {i: [j for j, _ in g.neighbors(i) if g.atoms[j].el == "C"] for i in cs}
    found = set()

    def dfs(start, u, path):
        if len(path) == 6:
            if start in adj[u]:
                found.add(frozenset(path))
            return
        for v in adj[u]:
            if v not in path and v > start:
                dfs(start, v, path + [v])
    for s in cs:
        dfs(s, s, [s])
    out = []
    for ring in found:
        ok = all(sum(1 for j, o in g.neighbors(i) if j in ring and o == 2) == 1 for i in ring)
        if ok:
            out.append(sorted(ring))
    return out


def groups_of(g):
    """Danh sách nhóm chức: (tên, mã nguyên tử tạo nên nhóm, mã nguyên tử C neo của nhóm hoặc None)."""
    out, used = [], set()
    rings = benzene_rings(g)
    arom = {x for r in rings for x in r}
    for c, a in g.atoms.items():
        if a.el != "C":
            continue
        ods = _o_double(g, c)
        if ods:
            o = ods[0]
            nbr = [(j, oo) for j, oo in g.neighbors(c) if j != o]
            oh = [j for j, oo in nbr if g.atoms[j].el == "O" and oo == 1 and g.total_h(j) == 1 and len(g.neighbors(j)) == 1]
            oe = [j for j, oo in nbr if g.atoms[j].el == "O" and oo == 1 and g.total_h(j) == 0 and len(g.neighbors(j)) == 2]
            nn = [j for j, oo in nbr if g.atoms[j].el == "N" and oo == 1]
            if oh:
                out.append(("axit cacboxylic", [c, o, oh[0]], c)); used |= {o, oh[0]}
            elif oe:
                out.append(("este", [c, o, oe[0]], c)); used |= {o, oe[0]}
            elif nn:
                out.append(("amit", [c, o, nn[0]], c)); used |= {o, nn[0]}
            elif g.total_h(c) >= 1:
                out.append(("anđehit", [c, o], c)); used |= {o}
            else:
                out.append(("xeton", [c, o], c)); used |= {o}
    for o, a in g.atoms.items():
        if a.el != "O" or o in used:
            continue
        nb = g.neighbors(o)
        if a.charge:
            continue
        if g.total_h(o) == 1 and len(nb) == 1 and nb[0][1] == 1 and g.atoms[nb[0][0]].el == "C":
            c = nb[0][0]
            out.append(("phenol" if c in arom else "ancol", [o], c))
        elif g.total_h(o) == 0 and len(nb) == 2 and all(oo == 1 and g.atoms[j].el == "C" for j, oo in nb):
            out.append(("ete", [o], nb[0][0]))
    for n, a in g.atoms.items():
        if a.el != "N":
            continue
        nb = g.neighbors(n)
        if a.charge == 1 and sum(1 for j, _ in nb if g.atoms[j].el == "O") == 2:
            c = [j for j, _ in nb if g.atoms[j].el == "C"]
            out.append(("nitro", [n] + [j for j, _ in nb if g.atoms[j].el == "O"], c[0] if c else None))
        elif n not in used and all(oo == 1 for _, oo in nb) and any(g.atoms[j].el == "C" for j, _ in nb):
            out.append(("amin", [n], [j for j, _ in nb if g.atoms[j].el == "C"][0]))
    for x, a in g.atoms.items():
        if a.el in ("F", "Cl", "Br", "I"):
            nb = g.neighbors(x)
            if nb and g.atoms[nb[0][0]].el == "C":
                out.append(("dẫn xuất halogen", [x], nb[0][0]))
    for b, o in g.bonds.items():
        i, j = tuple(sorted(b))
        if g.atoms[i].el == "C" and g.atoms[j].el == "C":
            if o == 2 and not (i in arom and j in arom):
                out.append(("anken (C=C)", [i, j], i))
            elif o == 3:
                out.append(("ankin (C≡C)", [i, j], i))
    for r in rings:
        out.append(("vòng benzen", r, None))
    nr = g.n_rings() - len(rings)
    if nr > 0:
        out.append(("vòng no", [], None))
    return out


def group_names(g):
    return Counter(n for n, _, _ in groups_of(g))


def group_locants(g):
    """Vị trí (số thứ tự cacbon trên mạch chính) của từng nhóm chức; mạch chọn theo hướng cho số nhỏ nhất. None nếu không xác định được."""
    chain = carbon_chain(g)
    if not chain:
        return None
    gs = [(n, c) for n, _, c in groups_of(g) if c is not None and n not in ("vòng benzen", "vòng no")]
    best = None
    for ch in (chain, chain[::-1]):
        pos = {c: k + 1 for k, c in enumerate(ch)}
        loc = sorted((n, pos.get(c)) for n, c in gs)
        key = tuple(x[1] if x[1] is not None else 99 for x in sorted(loc, key=lambda t: (t[1] is None, t[1] or 0)))
        if best is None or key < best[0]:
            best = (key, loc)
    return {"chuoi": len(chain), "nhom": best[1]}


# ------------------------------------------------------------------ chẩn đoán
def _err(code, atoms=(), bonds=(), cause="", detail=None, verified=True):
    return {"ma": code, "ten": ERR_NAMES[code], "atoms": sorted(set(atoms)), "bonds": list(bonds), "nguyen_nhan": cause,
            "quy_tac": RULES[code], "chi_tiet": detail or {}, "da_kiem_chung": verified}


def _fmt_delta(d):
    return ", ".join(f"{'thừa' if v > 0 else 'thiếu'} {abs(v)} nguyên tử {k}" for k, v in d.items() if v)


def diagnose(student, target, confirmed=True, warnings=()):
    """So sánh cấu trúc học sinh (MolGraph, giữ nguyên lỗi) với cấu trúc đúng của đề.

    Trả về {"trang_thai": "dung"|"sai"|"khong_du_thong_tin", "loi": [...], "loi_chinh": mã hoặc None, ...}.
    """
    res = {"trang_thai": "sai", "loi": [], "loi_chinh": None, "ct_hoc_sinh": student.hill() if student.atoms else "",
           "ct_dap_an": target.hill(), "da_xac_nhan": bool(confirmed)}
    errs = res["loi"]
    # 1. đủ căn cứ để kết luận không?
    unsupported = sorted({a.el for a in student.atoms.values() if a.el not in VALENCES})
    if not student.atoms:
        errs.append(_err("khong_du_thong_tin", cause="Chưa đọc được nguyên tử nào trong bài làm.", verified=False))
    elif unsupported:
        errs.append(_err("khong_du_thong_tin", cause="Có nguyên tố MolSnap chưa hỗ trợ: " + ", ".join(unsupported), verified=False))
    elif not student.is_connected():
        errs.append(_err("khong_du_thong_tin", atoms=[c[0] for c in student.components()],
                         cause="Hình có các phần rời nhau, chưa nối thành một phân tử. Có thể em quên một liên kết hoặc ảnh bị đọc thiếu nét nối.",
                         verified=False))
    if errs:
        res["trang_thai"] = "khong_du_thong_tin"
        res["loi_chinh"] = "khong_du_thong_tin"
        return res
    # 2. hóa trị
    vi = student.valence_issues()
    for v in vi:
        want = "/".join(map(str, v["cho_phep"])) or "?"
        how = {"thua": "vượt quá", "thieu": "chưa đủ", "khong_khop": "không khớp", "khong_ho_tro": "chưa hỗ trợ"}[v["loai"]]
        errs.append(_err("sai_hoa_tri", atoms=[v["id"]],
                         cause=f"Nguyên tử {v['el']} có tổng {v['thuc_te']} liên kết (kể cả liên kết tới H), {how} hóa trị {want}.",
                         detail={"nguyen_to": v["el"], "thuc_te": v["thuc_te"], "cho_phep": list(v["cho_phep"]), "loai": v["loai"]}, verified=confirmed))
    # 3. số nguyên tử
    hs, ht = Counter(student.heavy_counts()), Counter(target.heavy_counts())
    delta = {k: hs.get(k, 0) - ht.get(k, 0) for k in sorted(set(hs) | set(ht)) if hs.get(k, 0) != ht.get(k, 0)}
    if delta:
        errs.append(_err("thieu_thua_nguyen_tu", cause="So với chất cần viết, hình em vẽ " + _fmt_delta(delta) + ".",
                         detail={"chenh_lech": delta}, verified=confirmed))
    if vi:   # cấu trúc chưa hợp lệ: không kết luận về đồng phân hay bậc liên kết
        res["ghi_chu"] = "Hãy sửa lỗi hóa trị trước, sau đó MolSnap sẽ kiểm tra tiếp các lỗi khác."
        return _finish(res, confirmed)
    if delta:
        return _finish(res, confirmed)
    # 4. cùng nguyên tử nặng: so H, khung, nhóm chức
    fs, ft = student.formula(), target.formula()
    h_diff = fs.get("H", 0) - ft.get("H", 0)
    sk_s, map_s = canonical_map(student, "skeleton")
    sk_t, map_t = canonical_map(target, "skeleton")
    same_skel = sk_s == sk_t
    gs, gt = group_names(student), group_names(target)
    if canonical(student) == canonical(target):
        res["trang_thai"] = "dung"
        return res
    if h_diff:
        if same_skel:
            errs.append(_bond_order_err(student, target, map_s, map_t, confirmed, h_diff))
        errs.append(_err("sai_cong_thuc", cause=f"Hình em vẽ có {fs.get('H', 0)} nguyên tử H, chất cần viết có {ft.get('H', 0)} nguyên tử H "
                         f"({'thừa' if h_diff > 0 else 'thiếu'} {abs(h_diff)}).", detail={"h_hoc_sinh": fs.get("H", 0), "h_dap_an": ft.get("H", 0)}, verified=confirmed))
        return _finish(res, confirmed)
    same_orders = Counter(student.bonds.values()) == Counter(target.bonds.values())
    if same_skel and not (gs == gt and same_orders):
        if gs == gt:
            errs.append(_bond_order_err(student, target, map_s, map_t, confirmed, 0))
        else:
            errs.append(_function_err(student, target, gs, gt, confirmed))
        return _finish(res, confirmed)
    if gs != gt:
        errs.append(_function_err(student, target, gs, gt, confirmed))
        return _finish(res, confirmed)
    if canonical(student, "carbon") == canonical(target, "carbon"):
        ls, lt = group_locants(student), group_locants(target)
        atoms = [x for n, a, _ in groups_of(student) for x in a if n not in ("vòng benzen", "vòng no")]
        detail = {"nhom": sorted(gs), "vi_tri_hoc_sinh": [list(x) for x in ls["nhom"]] if ls else None, "vi_tri_dung": [list(x) for x in lt["nhom"]] if lt else None,
                  "mach": (lt or {}).get("chuoi")}
        errs.append(_err("sai_vi_tri_nhom_chuc", atoms=atoms,
                         cause="Mạch cacbon và loại nhóm chức đều đúng nhưng nhóm chức hoặc liên kết bội gắn vào cacbon khác với chất cần viết.",
                         detail=detail, verified=confirmed))
    else:
        cs, ct = carbon_chain(student), carbon_chain(target)
        branch = [c for c, a in student.atoms.items() if a.el == "C" and cs and c not in cs]
        errs.append(_err("sai_mach_cacbon", atoms=branch,
                         cause="Các nhóm chức đúng loại nhưng cách sắp xếp mạch cacbon (thẳng hay phân nhánh) khác với chất cần viết.",
                         detail={"mach_hoc_sinh": len(cs) if cs else None, "mach_dung": len(ct) if ct else None,
                                 "nhanh_hoc_sinh": len(branch), "nhanh_dung": (sum(1 for a in target.atoms.values() if a.el == "C") - len(ct)) if ct else None},
                         verified=confirmed))
    return _finish(res, confirmed)


def _bond_order_err(student, target, map_s, map_t, confirmed, h_diff):
    """Các liên kết khác bậc giữa hai cấu trúc có cùng khung (vị trí gần đúng nếu khung có đối xứng)."""
    pos_s = {a: k for k, a in enumerate(map_s)}
    pos_t = {a: k for k, a in enumerate(map_t)}
    tb = {frozenset((pos_t[i], pos_t[j])): o for b, o in target.bonds.items() for i, j in [tuple(b)]}
    bad = []
    for b, o in student.bonds.items():
        i, j = tuple(b)
        to = tb.get(frozenset((pos_s[i], pos_s[j])))
        if to is not None and to != o:
            bad.append((i, j, o, to))
    nm = {1: "đơn", 2: "đôi", 3: "ba"}
    txt = "; ".join(f"liên kết {nm[o]} (đúng ra là liên kết {nm[to]})" for _, _, o, to in bad[:3])
    return _err("sai_bac_lien_ket", atoms=[x for i, j, _, _ in bad for x in (i, j)], bonds=[(i, j) for i, j, _, _ in bad],
                cause="Khung nguyên tử đúng nhưng bậc liên kết chưa đúng: có " + (txt or "liên kết khác bậc") + ".",
                detail={"khac_bac": [{"tu": nm[o], "thanh": nm[to]} for _, _, o, to in bad], "chenh_h": h_diff}, verified=confirmed)


def _function_err(student, target, gs, gt, confirmed):
    only_s, only_t = gs - gt, gt - gs
    atoms = [x for n, a, _ in groups_of(student) if n in only_s for x in a]
    return _err("nham_dong_phan", atoms=atoms,
                cause="Hình em vẽ có nhóm " + (", ".join(sorted(only_s)) or "(không có nhóm chức đặc trưng)") + " còn chất cần viết có nhóm "
                + (", ".join(sorted(only_t)) or "(không có nhóm chức đặc trưng)") + ". Hai chất cùng công thức phân tử nhưng khác loại nhóm chức.",
                detail={"nhom_hoc_sinh": sorted(gs.elements()), "nhom_dap_an": sorted(gt.elements()), "chi_hoc_sinh": sorted(only_s), "chi_dap_an": sorted(only_t)},
                verified=confirmed)


def _finish(res, confirmed):
    errs = res["loi"]
    errs.sort(key=lambda e: PRIORITY.index(e["ma"]))
    res["loi_chinh"] = errs[0]["ma"] if errs else None
    if not errs:   # hợp lệ, cùng công thức, không phân loại được
        errs.append(_err("sai_yeu_cau_de", cause="Cấu trúc em vẽ hợp lệ nhưng chưa trùng với chất đề bài yêu cầu.", verified=confirmed))
        res["loi_chinh"] = "sai_yeu_cau_de"
    return res
