"""Sinh đồng phân cấu tạo thuần Python (không RDKit).

Mục đích: kiểm toán LOGIC của thuật toán đếm đồng phân trong app (thêm từng nguyên tử vào đồ thị liên thông, cắt tỉa theo số liên kết,
loại trùng bằng dạng chuẩn). Cùng logic, khác bộ chuẩn hóa: ở đây dùng molsnap_core.graph.canonical thay cho RDKit.
Nếu bản này cho đúng số liệu chuẩn trong tài liệu thì thiết kế thuật toán đúng; phần còn lại cần kiểm tra là lớp RDKit của app.
Phạm vi: nguyên tử trung hòa với hóa trị cố định (C 4, N 3, O 2, S 2, halogen 1). Không có điện tích, không có hóa trị cao (nitro, sunfat...).
"""
import time
from .graph import MolGraph, canonical

VALENCE = {"C": 4, "N": 3, "O": 2, "S": 2, "F": 1, "Cl": 1, "Br": 1, "I": 1}


class TooBig(Exception):
    pass


def parse_formula(s):
    import re
    toks = re.findall(r"([A-Z][a-z]?)(\d*)", s)
    if not toks or "".join(a + b for a, b in toks) != s:
        raise ValueError("không phải công thức phân tử")
    c = {}
    for a, b in toks:
        c[a] = c.get(a, 0) + (int(b) if b else 1)
    nH = c.pop("H", 0)
    bad = [e for e in c if e not in VALENCE]
    if bad or not c:
        raise ValueError("nguyên tố chưa hỗ trợ: " + ", ".join(bad or ["?"]))
    return c, nH


def _key(atoms, edges):
    g = MolGraph()
    for e in atoms:
        g.add_atom(e, None)
    for i, j, o in edges:
        g.add_bond(i + 1, j + 1, o)
    return canonical(g)


def enumerate_isomers(counts, nH, time_limit=60, max_graphs=500000, strict=False):
    """Trả về tập chuỗi chuẩn của MỌI đồ thị liên thông đúng hóa trị (không trùng). strict: mạch hở hoặc một vòng, không O–O."""
    els = sorted(counts)
    N = sum(counts.values())
    sigma = sum(VALENCE[e] * counts[e] for e in els)
    if sigma - nH < 0 or (sigma - nH) % 2:
        return set()
    B = (sigma - nH) // 2
    if B < N - 1:
        return set()
    t0, memo, total = time.time(), {}, [0]

    def build(sub):
        if sub in memo:
            return memo[sub]
        n = sum(sub)
        res = {}
        if n == 1:
            e = els[[i for i, c in enumerate(sub) if c][0]]
            res[_key([e], [])] = ([e], [])
            memo[sub] = res
            return res
        upper = B - (N - n)
        for i, c in enumerate(sub):
            if not c:
                continue
            prev = list(sub)
            prev[i] -= 1
            e, vn = els[i], VALENCE[els[i]]
            for atoms, edges in list(build(tuple(prev)).values()):
                T = sum(o for _, _, o in edges)
                if T + 1 > upper:
                    continue
                used = [0] * len(atoms)
                for a, b, o in edges:
                    used[a] += o
                    used[b] += o
                free = [VALENCE[atoms[k]] - used[k] for k in range(len(atoms))]
                k = len(atoms)

                def rec(j, rem_new, added, att):
                    if time.time() - t0 > time_limit:
                        raise TooBig("time")
                    if j == k:
                        if att and T + added <= upper and (n < N or T + added == B):
                            na, ne = atoms + [e], edges + [(a, k, o) for a, o in att]
                            if strict:
                                if len(ne) - len(na) + 1 > 1:
                                    return
                                if e == "O" and any(atoms[a] == "O" for a, _ in att):
                                    return
                            key = _key(na, ne)
                            if key not in res:
                                res[key] = (na, ne)
                                total[0] += 1
                                if total[0] > max_graphs:
                                    raise TooBig("size")
                        return
                    rec(j + 1, rem_new, added, att)
                    for o in (1, 2, 3):
                        if o <= rem_new and o <= free[j] and T + added + o <= upper:
                            rec(j + 1, rem_new - o, added + o, att + [(j, o)])
                rec(0, vn, 0, [])
        memo[sub] = res
        return res

    return set(build(tuple(counts[e] for e in els)).keys())


def count_isomers(formula, **kw):
    c, nH = parse_formula(formula)
    return len(enumerate_isomers(c, nH, **kw))


# ---- Số liệu chuẩn độc lập (tài liệu tham khảo, KHÔNG sinh từ MolSnap) ----
# Số đồng phân cấu tạo (không tính lập thể) của công thức; nguồn và cách đếm tay ghi trong benchmarks/README.md
GOLD_COUNTS = {
    "CH4": 1, "C2H6": 1, "C3H8": 1, "C4H10": 2, "C5H12": 3, "C6H14": 5, "C7H16": 9, "C8H18": 18,   # OEIS A000602
    "C2H6O": 2, "C3H8O": 3, "C4H10O": 7, "C5H12O": 14,                                              # ancol + ete (đếm tay: 1+1, 2+1, 4+3, 8+6)
    "C4H9Cl": 4, "C5H11Cl": 8,                                                                       # số gốc ankyl C4H9 = 4, C5H11 = 8
    "C3H6": 2, "C4H8": 5, "C5H10": 10,                                                               # anken + xicloankan
    "C3H6O": 9,                                                                                      # đếm tay: 2 cacbonyl + 4 hở có C=C + 3 vòng
}


def scope_warnings(counts, nH=0):
    """Cảnh báo trung thực khi công thức có thể có đồng phân nằm ngoài phạm vi sinh của thuật toán."""
    w = []
    if counts.get("N") and counts.get("O", 0) >= 2:
        w.append("Kết quả CHƯA gồm hợp chất có nhóm nitro (N⁺–O⁻) và N-oxit, vì thuật toán chỉ sinh cấu trúc trung hòa với N hóa trị 3.")
    if counts.get("S"):
        w.append("Lưu huỳnh chỉ được tính hóa trị 2: kết quả CHƯA gồm sunfoxit, sunfon, axit sunfonic, sunfat...")
    return w
