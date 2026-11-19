"""Đọc cấu trúc từ ba nguồn: SMILES rút gọn, công thức thu gọn của học sinh, đồ thị AI chép từ ảnh.
Cả ba đều KHÔNG tự sửa lỗi hóa trị: cấu trúc sai được giữ nguyên để ErrorLab phân tích."""
import re
from .graph import MolGraph, VALENCES, fold_explicit_h


class ParseError(ValueError):
    pass


# ------------------------------------------------------------------ SMILES rút gọn
_ORG = ("Cl", "Br", "C", "N", "O", "P", "S", "F", "I", "c", "n", "o", "s")


def from_smiles(smi):
    """SMILES tập con: nguyên tử hữu cơ, [nguyên tử], nhánh (), vòng 1-9, liên kết - = #, vòng thơm c/n kiểu benzen."""
    g, prev, stack, rings, arom = MolGraph(), None, [], {}, set()
    pending = None        # liên kết đang chờ giữa hai nguyên tử
    i, s = 0, smi.strip()
    if not s:
        raise ParseError("rỗng")
    while i < len(s):
        ch = s[i]
        if ch in "-=#:":
            pending = {"-": 1, "=": 2, "#": 3, ":": "a"}[ch]
            i += 1
        elif ch == "(":
            if prev is None:
                raise ParseError("nhánh không có nguyên tử đứng trước")
            stack.append(prev)
            i += 1
        elif ch == ")":
            if not stack:
                raise ParseError("thừa dấu ngoặc đóng")
            prev = stack.pop()
            i += 1
        elif ch.isdigit() or ch == "%":
            if ch == "%":
                num, i = s[i + 1:i + 3], i + 3
            else:
                num, i = ch, i + 1
            if prev is None:
                raise ParseError("số đóng vòng đứng sai chỗ")
            if num in rings:
                j, ob = rings.pop(num)
                o = pending or ob
                _bond(g, prev, j, o, arom)
                pending = None
            else:
                rings[num] = (prev, pending)
                pending = None
        else:
            if ch == "[":
                k = s.find("]", i)
                if k < 0:
                    raise ParseError("thiếu ]")
                m = re.fullmatch(r"([A-Z][a-z]?|[cnos])(H(\d*))?([+-]\d*|\+\+|--)?", s[i + 1:k])
                if not m:
                    raise ParseError("nguyên tử trong [ ] không đọc được: " + s[i:k + 1])
                el, hh, hn, chg = m.group(1), m.group(2), m.group(3), m.group(4)
                if (el.upper() if el in "cnos" else el) not in VALENCES:
                    raise ParseError("nguyên tố chưa hỗ trợ: " + el)
                h = (int(hn) if hn else 1) if hh else 0
                charge = 0
                if chg:
                    sign = 1 if chg[0] == "+" else -1
                    charge = sign * (int(chg[1:]) if chg[1:].isdigit() else len(chg))
                i = k + 1
                a = g.add_atom(el.upper() if el in "cnos" else el, h, charge)
                if el in "cnos":
                    arom.add(a)
            else:
                el = next((e for e in _ORG if s.startswith(e, i)), None)
                if el is None:
                    raise ParseError(f"ký hiệu lạ ở vị trí {i + 1}: {ch}")
                i += len(el)
                a = g.add_atom(el.upper() if el in "cnos" else el, None)
                if el in "cnos":
                    arom.add(a)
            if prev is not None:
                _bond(g, prev, a, pending, arom)
            pending = None
            prev = a
    if stack:
        raise ParseError("thiếu dấu ngoặc đóng")
    if rings:
        raise ParseError("vòng chưa đóng")
    _kekulize(g, arom)
    return g


def _bond(g, i, j, o, arom):
    if o is None:
        o = "a" if (i in arom and j in arom) else 1
    if o == "a":
        g.bonds[frozenset((i, j))] = "a"
    else:
        g.add_bond(i, j, o)


def _kekulize(g, arom):
    ab = [b for b, o in g.bonds.items() if o == "a"]
    if not ab:
        return
    atoms = sorted({x for b in ab for x in b})
    for a in atoms:
        if g.atoms[a].el not in ("C", "N") or g.atoms[a].h:
            raise ParseError("vòng thơm chỉ hỗ trợ kiểu benzen")
    adj = {a: [] for a in atoms}
    for b in ab:
        i, j = tuple(b)
        adj[i].append(j)
        adj[j].append(i)
    match = {}

    def solve(k):
        if k == len(atoms):
            return True
        a = atoms[k]
        if a in match:
            return solve(k + 1)
        for v in adj[a]:
            if v not in match:
                match[a], match[v] = v, a
                if solve(k + 1):
                    return True
                del match[a], match[v]
        return False
    if not solve(0):
        raise ParseError("vòng thơm không sắp xếp được các nối đôi xen kẽ")
    for b in ab:
        i, j = tuple(b)
        g.bonds[b] = 2 if match.get(i) == j else 1


# ------------------------------------------------------------------ công thức thu gọn của học sinh
_BONDS = {"-": 1, "–": 1, "—": 1, "=": 2, "≡": 3, "#": 3}
_TOK = re.compile(r"\s*(HCOO|COOH|COO|CHO|NO2|CO(?![A-Za-z])|[A-Z][a-z]?)(\d*)")


def _group(g, tok, n):
    """Tạo nhóm nguyên tử, trả về (mã nguyên tử nối với phần trước, mã nối với phần sau, mã nhận nhánh)."""
    if tok == "COOH":
        c = g.add_atom("C", 0); o1 = g.add_atom("O", 0); o2 = g.add_atom("O", 1)
        g.add_bond(c, o1, 2); g.add_bond(c, o2, 1)
        return c, None, c
    if tok == "CHO":
        c = g.add_atom("C", 1); o = g.add_atom("O", 0)
        g.add_bond(c, o, 2)
        return c, None, c
    if tok == "COO":
        c = g.add_atom("C", 0); o1 = g.add_atom("O", 0); o2 = g.add_atom("O", 0)
        g.add_bond(c, o1, 2); g.add_bond(c, o2, 1)
        return c, o2, c
    if tok == "HCOO":
        c = g.add_atom("C", 1); o1 = g.add_atom("O", 0); o2 = g.add_atom("O", 0)
        g.add_bond(c, o1, 2); g.add_bond(c, o2, 1)
        return None, o2, c
    if tok == "CO":
        c = g.add_atom("C", 0); o = g.add_atom("O", 0)
        g.add_bond(c, o, 2)
        return c, c, c
    if tok == "NO2":
        nn = g.add_atom("N", 0, 1); o1 = g.add_atom("O", 0); o2 = g.add_atom("O", 0, -1)
        g.add_bond(nn, o1, 2); g.add_bond(nn, o2, 1)
        return nn, None, nn
    raise ParseError("nhóm không hỗ trợ: " + tok)


def from_condensed(text):
    """Công thức thu gọn dạng chuỗi như CH3-CH(OH)-CH3, CH2=CH-CH3, CH3COOH, CH3-CO-CH3, HCOOCH3.
    Số H viết ngay sau ký hiệu (CH3, NH2, OH). Nguyên tử không ghi H thì có 0 H (đúng như hình học sinh viết)."""
    s = (text or "").replace("₀", "0").replace("₁", "1").replace("₂", "2").replace("₃", "3").replace("₄", "4") \
        .replace("₅", "5").replace("₆", "6").replace("₇", "7").replace("₈", "8").replace("₉", "9").strip()
    if not s:
        raise ParseError("rỗng")
    g = MolGraph()
    pos = [0]

    def read_chain(attach, first_bond=1):
        """Đọc một dãy nhóm. attach: nguyên tử đã có để nối vào nhóm đầu tiên (hoặc None)."""
        prev_right, bond, first_main = attach, first_bond, None
        main, dangling = attach, False
        while pos[0] < len(s):
            ch = s[pos[0]]
            if ch in _BONDS:
                bond = _BONDS[ch]
                dangling = True
                pos[0] += 1
                continue
            if ch == "(":
                if main is None:
                    raise ParseError("nhánh đứng sai chỗ")
                pos[0] += 1
                b0 = 1
                if pos[0] < len(s) and s[pos[0]] in _BONDS:
                    b0 = _BONDS[s[pos[0]]]
                    pos[0] += 1
                read_chain(main, b0)
                dangling = False
                if pos[0] >= len(s) or s[pos[0]] != ")":
                    raise ParseError("thiếu dấu ngoặc đóng")
                pos[0] += 1
                continue
            if ch == ")":
                if dangling:
                    raise ParseError("có dấu liên kết chưa nối với nguyên tử nào")
                return first_main
            if ch.isspace():
                pos[0] += 1
                continue
            m = _TOK.match(s, pos[0])
            if not m:
                raise ParseError(f"không đọc được ký hiệu ở vị trí {pos[0] + 1}: {ch}")
            tok, num = m.group(1), m.group(2)
            pos[0] = m.end()
            if num and tok in ("F", "Cl", "Br", "I") and main is not None and not dangling:   # CCl3, CHCl3: n nguyên tử halogen gắn vào nguyên tử đứng trước
                for _ in range(int(num)):
                    g.add_bond(main, g.add_atom(tok, 0), 1)
                continue
            if tok in ("COOH", "CHO", "COO", "HCOO", "NO2", "CO"):
                left, right, main_atom = _group(g, tok, num)
            else:
                el = tok
                if el not in VALENCES:
                    raise ParseError("nguyên tố không hỗ trợ: " + el)
                h = 0
                # H ghi ngay sau ký hiệu: CH3, NH2, OH, SH. Tách "H" + số khỏi phần còn lại.
                hm = re.match(r"H(\d*)", s[pos[0]:]) if not num else None
                if hm and el in ("C", "N", "O", "S", "P"):
                    h = int(hm.group(1)) if hm.group(1) else 1
                    pos[0] += hm.end()
                elif num:
                    raise ParseError(f"số {num} đứng sau {el} không rõ nghĩa (viết số H ngay sau chữ H, ví dụ CH3)")
                a = g.add_atom(el, h)
                left = right = main_atom = a
            if left is None and prev_right is not None:
                raise ParseError("nhóm " + tok + " chỉ được đứng ở đầu công thức")
            if prev_right is not None and left is not None:
                g.add_bond(prev_right, left, bond)
            elif prev_right is None and bond not in (1,):
                pass
            if first_main is None:
                first_main = main_atom
            prev_right, main, bond, dangling = right, main_atom, 1, False
            if right is None:   # nhóm kết thúc (COOH, CHO): chỉ cho phép nhánh/đóng ngoặc/hết chuỗi
                nxt = s[pos[0]] if pos[0] < len(s) else ""
                if nxt and nxt not in ")":
                    raise ParseError("sau nhóm " + tok + " không còn nối được nguyên tử nào")
        if dangling:
            raise ParseError("có dấu liên kết chưa nối với nguyên tử nào")
        return first_main
    read_chain(None)
    if pos[0] != len(s):
        raise ParseError("thừa dấu ngoặc đóng")
    if not g.atoms:
        raise ParseError("rỗng")
    return fold_explicit_h(g)


# ------------------------------------------------------------------ đồ thị do AI chép từ ảnh
def from_ai_graph(d):
    """d = {"atoms": [{"id", "el", "h"}], "bonds": [[i, j, bậc]], "ghi_chu": "..."}.
    Trả về (MolGraph, danh sách cảnh báo về chất lượng nhận dạng). Không sửa cấu trúc."""
    if not isinstance(d, dict):
        raise ParseError("kết quả nhận dạng không hợp lệ")
    warn, g, ids = [], MolGraph(), {}
    for a in d.get("atoms") or []:
        try:
            el = str(a.get("el", "C")).strip()
            el = el[:1].upper() + el[1:].lower()
            h = a.get("h")
            h = int(h) if isinstance(h, (int, float)) and not isinstance(h, bool) else None
            ids[int(a["id"])] = g.add_atom(el, h, int(a.get("charge", 0) or 0))
        except Exception:
            raise ParseError("một nguyên tử trong kết quả nhận dạng bị lỗi")
    if not g.atoms:
        raise ParseError("không nhận ra nguyên tử nào trong ảnh")
    for b in d.get("bonds") or []:
        try:
            i, j, o = int(b[0]), int(b[1]), int(b[2])
            if i not in ids or j not in ids:
                warn.append("có liên kết nối tới nguyên tử không tồn tại")
                continue
            if i == j:
                warn.append("có liên kết nối một nguyên tử với chính nó")
                continue
            if frozenset((ids[i], ids[j])) in g.bonds:
                warn.append("có hai liên kết trùng giữa cùng một cặp nguyên tử")
                continue
            g.add_bond(ids[i], ids[j], o)
        except Exception:
            warn.append("một liên kết không đọc được")
    if not g.is_connected():
        warn.append("hình có các phần rời nhau (không nối liền thành một phân tử)")
    unknown = [a.el for a in g.atoms.values() if a.el not in VALENCES]
    if unknown:
        warn.append("nguyên tố chưa hỗ trợ: " + ", ".join(sorted(set(unknown))))
    return fold_explicit_h(g), warn
