"""Ngân hàng bài tập viết công thức cấu tạo.

Mỗi bài có: tên chất (đáp án theo SGK), cấu trúc đúng (SMILES rút gọn), công thức phân tử chuẩn do người soạn kiểm tra
độc lập (tests/ dùng để phát hiện lỗi gõ trong cấu trúc), tên gọi khác và thẻ kỹ năng.
Thẻ kỹ năng "gây nhầm" được tính bằng ErrorLab từ các đồng phân khác trong cùng ngân hàng, không gán tay.
"""
from .parse import from_smiles
from .diagnose import diagnose, group_names

# (tên, SMILES, tên khác, công thức phân tử chuẩn)
_RAW = [
    ("metan", "C", [], "CH4"), ("etan", "CC", [], "C2H6"), ("propan", "CCC", [], "C3H8"), ("butan", "CCCC", ["n-butan"], "C4H10"),
    ("2-metylpropan", "CC(C)C", ["isobutan"], "C4H10"), ("pentan", "CCCCC", ["n-pentan"], "C5H12"),
    ("2-metylbutan", "CCC(C)C", ["isopentan"], "C5H12"), ("2,2-đimetylpropan", "CC(C)(C)C", ["neopentan"], "C5H12"),
    ("eten", "C=C", ["etilen"], "C2H4"), ("propen", "C=CC", ["propilen"], "C3H6"), ("but-1-en", "C=CCC", ["1-buten"], "C4H8"),
    ("but-2-en", "CC=CC", ["2-buten"], "C4H8"), ("etin", "C#C", ["axetilen"], "C2H2"), ("propin", "C#CC", [], "C3H4"),
    ("benzen", "c1ccccc1", [], "C6H6"), ("toluen", "Cc1ccccc1", ["metylbenzen"], "C7H8"), ("stiren", "C=Cc1ccccc1", ["vinylbenzen"], "C8H8"),
    ("phenol", "Oc1ccccc1", ["hiđroxibenzen"], "C6H6O"), ("anilin", "Nc1ccccc1", ["phenylamin"], "C6H7N"),
    ("metanol", "CO", ["ancol metylic"], "CH4O"), ("etanol", "CCO", ["ancol etylic"], "C2H6O"),
    ("propan-1-ol", "CCCO", ["ancol propylic"], "C3H8O"), ("propan-2-ol", "CC(C)O", ["ancol isopropylic"], "C3H8O"),
    ("butan-1-ol", "CCCCO", [], "C4H10O"), ("etylen glicol", "OCCO", ["etan-1,2-điol"], "C2H6O2"),
    ("glixerol", "OCC(O)CO", ["glixerin", "propan-1,2,3-triol"], "C3H8O3"),
    ("metanal", "C=O", ["fomanđehit", "anđehit fomic"], "CH2O"), ("etanal", "CC=O", ["anđehit axetic", "axetanđehit"], "C2H4O"),
    ("propanon", "CC(C)=O", ["axeton"], "C3H6O"), ("axit metanoic", "OC=O", ["axit fomic"], "CH2O2"),
    ("axit etanoic", "CC(=O)O", ["axit axetic"], "C2H4O2"), ("axit propanoic", "CCC(=O)O", ["axit propionic"], "C3H6O2"),
    ("axit benzoic", "OC(=O)c1ccccc1", [], "C7H6O2"), ("metyl axetat", "COC(C)=O", ["metyl etanoat"], "C3H6O2"),
    ("etyl axetat", "CCOC(C)=O", ["etyl etanoat"], "C4H8O2"), ("metylamin", "CN", ["metanamin"], "CH5N"), ("etylamin", "CCN", ["etanamin"], "C2H7N"),
    ("glyxin", "NCC(=O)O", ["axit aminoaxetic"], "C2H5NO2"), ("alanin", "CC(N)C(=O)O", ["axit 2-aminopropanoic"], "C3H7NO2"),
    ("đimetyl ete", "COC", [], "C2H6O"), ("đietyl ete", "CCOCC", [], "C4H10O"), ("etyl clorua", "CCCl", ["cloetan"], "C2H5Cl"),
    ("clorofom", "ClC(Cl)Cl", ["triclometan"], "CHCl3"),
]


class Exercise:
    def __init__(self, idx, ten, smiles, alias, formula):
        self.idx, self.id, self.ten, self.smiles, self.alias, self.formula = idx, f"ex{idx:02d}", ten, smiles, alias, formula
        self.graph = from_smiles(smiles)
        self.n_heavy = len(self.graph.atoms)
        self.groups = sorted(group_names(self.graph).elements())
        self.skills, self.difficulty = [], 1


def _build():
    items = [Exercise(i, *r) for i, r in enumerate(_RAW)]
    by_formula = {}
    for e in items:
        by_formula.setdefault(e.graph.hill(), []).append(e)
    for e in items:
        sk = {"sai_hoa_tri", "thieu_thua_nguyen_tu"}
        if e.graph.formula().get("H") is not None and e.n_heavy > 1:
            sk.add("sai_cong_thuc")
        for p in by_formula[e.graph.hill()]:
            if p is not e:
                r = diagnose(p.graph, e.graph)
                if r["trang_thai"] == "sai" and r["loi_chinh"]:
                    sk.add(r["loi_chinh"])
        if any(o >= 2 for o in e.graph.bonds.values()):
            sk.add("sai_bac_lien_ket")
        e.skills = sorted(sk)
        branched = False
        from .graph import carbon_chain
        ch = carbon_chain(e.graph)
        ncarb = sum(1 for a in e.graph.atoms.values() if a.el == "C")
        if ch and len(ch) < ncarb:
            branched = True
        score = e.n_heavy // 3 + len(e.groups) + (1 if branched else 0) + (1 if e.graph.n_rings() else 0)
        e.difficulty = 1 if score <= 1 else 2 if score <= 3 else 3 if score <= 5 else 4
    return items


EXERCISES = _build()
BY_ID = {e.id: e for e in EXERCISES}
ALL_SKILLS = ["sai_hoa_tri", "thieu_thua_nguyen_tu", "sai_cong_thuc", "sai_bac_lien_ket", "sai_mach_cacbon", "nham_dong_phan", "sai_vi_tri_nhom_chuc"]
