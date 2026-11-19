"""Đồ thị phân tử thuần Python.

Điểm khác với việc chuẩn hóa bằng RDKit: đồ thị GIỮ NGUYÊN những gì học sinh vẽ, kể cả khi sai hóa trị.
Mỗi nguyên tử có thể ghi rõ số H (h = số nguyên) hoặc để H ngầm định (h = None, công thức khung).
"""
from collections import Counter

# Hóa trị được chấp nhận theo chương trình phổ thông (nguyên tử trung hòa).
VALENCES = {"H": (1,), "C": (4,), "N": (3,), "O": (2,), "F": (1,), "Cl": (1,), "Br": (1,), "I": (1,),
            "S": (2, 4, 6), "P": (3, 5)}
# Điện tích được hỗ trợ: (nguyên tố, điện tích) -> hóa trị
CHARGED = {("N", 1): (4,), ("O", -1): (1,), ("O", 1): (3,), ("N", -1): (2,)}


class Atom:
    __slots__ = ("id", "el", "h", "charge")

    def __init__(self, id, el, h=None, charge=0):
        self.id, self.el, self.h, self.charge = id, el, h, charge


class MolGraph:
    def __init__(self):
        self.atoms = {}      # id -> Atom
        self.bonds = {}      # frozenset({i, j}) -> bậc liên kết (1, 2, 3)
        self._next = 1

    # ---- dựng ----
    def add_atom(self, el, h=None, charge=0, id=None):
        if id is None:
            id = self._next
        self._next = max(self._next, id + 1)
        if id in self.atoms:
            raise ValueError(f"trùng mã nguyên tử {id}")
        self.atoms[id] = Atom(id, el, h, charge)
        return id

    def add_bond(self, i, j, order=1):
        if i == j or i not in self.atoms or j not in self.atoms:
            raise ValueError("liên kết không hợp lệ")
        if order not in (1, 2, 3):
            raise ValueError("bậc liên kết phải là 1, 2 hoặc 3")
        self.bonds[frozenset((i, j))] = order

    def copy(self):
        g = MolGraph()
        for a in self.atoms.values():
            g.add_atom(a.el, a.h, a.charge, a.id)
        g.bonds = dict(self.bonds)
        return g

    # ---- truy vấn ----
    def neighbors(self, i):
        out = []
        for b, o in self.bonds.items():
            if i in b:
                (j,) = tuple(b - {i})
                out.append((j, o))
        return sorted(out)

    def bond_sum(self, i):
        return sum(o for _, o in self.neighbors(i))

    def allowed(self, i):
        a = self.atoms[i]
        if a.charge:
            return CHARGED.get((a.el, a.charge))
        return VALENCES.get(a.el)

    def total_h(self, i):
        """Số H của nguyên tử: số đã ghi, hoặc (nếu để ngầm định) số H bổ sung cho đủ hóa trị thấp nhất có thể."""
        a = self.atoms[i]
        if a.h is not None:
            return a.h
        allowed = self.allowed(i)
        if not allowed:
            return 0
        bs = self.bond_sum(i)
        for v in allowed:
            if v >= bs:
                return v - bs
        return 0

    def formula(self):
        c = Counter()
        for i, a in self.atoms.items():
            c[a.el] += 1
            c["H"] += self.total_h(i)
        if not c["H"]:
            del c["H"]
        return dict(c)

    def hill(self):
        c = self.formula()
        order = (["C", "H"] if "C" in c else []) + sorted(k for k in c if k not in ("C", "H")) if "C" in c else sorted(c)
        return "".join(k + (str(c[k]) if c[k] > 1 else "") for k in order if k in c)

    def heavy_counts(self):
        return dict(Counter(a.el for a in self.atoms.values()))

    def components(self):
        seen, comps = set(), []
        for s in self.atoms:
            if s in seen:
                continue
            stack, comp = [s], []
            seen.add(s)
            while stack:
                u = stack.pop()
                comp.append(u)
                for v, _ in self.neighbors(u):
                    if v not in seen:
                        seen.add(v)
                        stack.append(v)
            comps.append(sorted(comp))
        return comps

    def is_connected(self):
        return len(self.components()) <= 1

    def n_rings(self):
        return len(self.bonds) - len(self.atoms) + len(self.components())

    # ---- kiểm tra hóa trị ----
    def valence_issues(self):
        """Danh sách vấn đề hóa trị. Mỗi phần tử: id, el, thuc_te, cho_phep, loai ('thua'|'thieu'|'khong_ho_tro'|'khong_khop')."""
        out = []
        for i, a in self.atoms.items():
            allowed = self.allowed(i)
            if not allowed:
                out.append({"id": i, "el": a.el, "thuc_te": self.bond_sum(i) + (a.h or 0), "cho_phep": (), "loai": "khong_ho_tro"})
                continue
            bs = self.bond_sum(i)
            if a.h is None:   # H ngầm định: chỉ có thể thừa liên kết
                if bs > max(allowed):
                    out.append({"id": i, "el": a.el, "thuc_te": bs, "cho_phep": allowed, "loai": "thua"})
                continue
            actual = bs + a.h
            if actual in allowed:
                continue
            if actual > max(allowed):
                kind = "thua"
            elif actual < min(allowed):
                kind = "thieu"
            else:
                kind = "khong_khop"
            out.append({"id": i, "el": a.el, "thuc_te": actual, "cho_phep": allowed, "loai": kind})
        return out


# ---------------------------------------------------------------- dạng chuẩn
class _TooMany(Exception):
    pass


def canonical(g, mode="full", leaf_limit=20000):
    return canonical_map(g, mode, leaf_limit)[0]


def canonical_map(g, mode="full", leaf_limit=20000):
    """Chuỗi chuẩn của đồ thị: hai đồ thị đẳng cấu thì có cùng chuỗi, và ngược lại.

    mode:
      "full"      nguyên tố, số H, điện tích và bậc liên kết (cấu tạo đầy đủ)
      "skeleton"  nguyên tố và liên kết, bỏ qua bậc liên kết và H (khung nguyên tử)
      "carbon"    chỉ các nguyên tử C và liên kết giữa chúng, bỏ qua bậc (khung cacbon)
    """
    atoms = [i for i, a in g.atoms.items() if mode != "carbon" or a.el == "C"]
    if not atoms:
        return "", []
    keep = set(atoms)
    adj = {i: [] for i in atoms}
    for b, o in g.bonds.items():
        i, j = tuple(b)
        if i in keep and j in keep:
            w = o if mode == "full" else 1
            adj[i].append((j, w))
            adj[j].append((i, w))

    def label(i):
        a = g.atoms[i]
        if mode == "full":
            return (a.el, g.total_h(i), a.charge)
        return (a.el, 0, 0)

    labels = {i: label(i) for i in atoms}
    uniq = sorted(set(labels.values()))
    base = {i: uniq.index(labels[i]) for i in atoms}

    def refine(col):
        while True:
            sig = {v: (col[v], tuple(sorted((col[u], w) for u, w in adj[v]))) for v in atoms}
            ranks = sorted(set(sig.values()))
            new = {v: ranks.index(sig[v]) for v in atoms}
            if len(set(new.values())) == len(set(col.values())):
                return new
            col = new

    best, leaves = [None], [0]

    def search(col):
        col = refine(col)
        groups = {}
        for v, c in col.items():
            groups.setdefault(c, []).append(v)
        if all(len(m) == 1 for m in groups.values()):
            leaves[0] += 1
            if leaves[0] > leaf_limit:
                raise _TooMany()
            order = sorted(atoms, key=lambda v: col[v])
            pos = {v: k for k, v in enumerate(order)}
            s = ".".join("{}{}{}".format(*labels[v][:1], labels[v][1], "" if not labels[v][2] else ("+" if labels[v][2] > 0 else "-")) for v in order)
            edges = sorted((min(pos[i], pos[j]), max(pos[i], pos[j]), w) for i in atoms for j, w in adj[i] if i < j)
            s += ";" + ",".join(f"{a}-{b}-{w}" for a, b, w in edges)
            if best[0] is None or s < best[0][0]:
                best[0] = (s, order)
            return
        target = min((c for c, m in groups.items() if len(m) > 1))
        for v in groups[target]:
            nc = {u: 2 * c + 1 for u, c in col.items()}
            nc[v] = 2 * col[v]
            search(nc)

    search(base)
    return best[0]


def same_structure(a, b):
    return canonical(a) == canonical(b)


def carbon_chain(g):
    """Mạch cacbon dài nhất (danh sách mã nguyên tử C) trong phần mạch hở; None nếu có vòng hoặc không có C."""
    cs = [i for i, a in g.atoms.items() if a.el == "C"]
    if not cs:
        return None
    adj = {i: [j for j, _ in g.neighbors(i) if g.atoms[j].el == "C"] for i in cs}
    if sum(len(v) for v in adj.values()) // 2 > len(cs) - len(_c_components(adj)):
        return None   # có vòng cacbon
    best = []

    def dfs(u, seen, path):
        nonlocal best
        if len(path) > len(best):
            best = list(path)
        for v in adj[u]:
            if v not in seen:
                seen.add(v)
                path.append(v)
                dfs(v, seen, path)
                path.pop()
                seen.discard(v)
    for s in cs:
        dfs(s, {s}, [s])
    return best


def _c_components(adj):
    seen, n = set(), []
    for s in adj:
        if s in seen:
            continue
        n.append(s)
        stack = [s]
        seen.add(s)
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
    return n


def fold_explicit_h(g):
    """Gộp các nguyên tử H vẽ riêng (liên kết đơn với đúng một nguyên tử nặng) vào số H của nguyên tử nặng đó.
    H nối với 0 hoặc từ 2 nguyên tử trở lên (hoặc liên kết bội) được GIỮ LẠI để kiểm tra hóa trị báo lỗi, không bị làm đẹp.
    Phân tử chỉ có H (H2) được giữ nguyên."""
    h = g.copy()
    if all(a.el == "H" for a in h.atoms.values()):
        return h
    for i in [i for i, a in h.atoms.items() if a.el == "H"]:
        nb = h.neighbors(i)
        if len(nb) == 1 and nb[0][1] == 1 and h.atoms[nb[0][0]].el != "H":
            j = nb[0][0]
            h.atoms[j].h = (h.atoms[j].h or 0) + 1 + (h.atoms[i].h or 0)
            del h.bonds[frozenset((i, j))]
            del h.atoms[i]
    return h
