"""Nạp các hàm thuần Python từ app.py để kiểm thử mà không chạy giao diện Streamlit.

Cách làm: đọc app.py bằng ast, lấy các định nghĩa cấp cao nhất cần thiết và các định nghĩa chúng phụ thuộc (đệ quy),
rồi chạy trong một không gian tên có st, Chem, ... được thay bằng đối tượng giả. Nhờ đó không cần Streamlit, RDKit hay mạng.
"""
import ast
import os
import re
from unittest import mock

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
_CACHE = {}


def _defs():
    if "defs" not in _CACHE:
        with open(APP, encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        defs = {}
        for i, n in enumerate(tree.body):
            names = []
            if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                names = [n.name]
            elif isinstance(n, ast.Assign):
                names = [t.id for t in n.targets if isinstance(t, ast.Name)]
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                names = [n.target.id]
            for nm in names:
                defs[nm] = (i, n)
        _CACHE["defs"] = defs
    return _CACHE["defs"]


def _free_names(node):
    return {x.id for x in ast.walk(node) if isinstance(x, ast.Name)}


def load(*wanted):
    """Trả về dict tên -> đối tượng cho các hàm/hằng cần dùng (kèm phụ thuộc)."""
    defs = _defs()
    need, stack = {}, list(wanted)
    while stack:
        nm = stack.pop()
        if nm in need or nm not in defs:
            continue
        need[nm] = defs[nm]
        stack.extend(_free_names(defs[nm][1]))
    class _FakeChem:
        @staticmethod
        def MolFromSmarts(x):
            return ("pat", x)
    ns = {"__builtins__": __builtins__, "__file__": APP, "st": mock.MagicMock(), "Chem": _FakeChem, "types": mock.MagicMock(), "errors": mock.MagicMock(),
          "components": mock.MagicMock(), "Draw": mock.MagicMock(), "Image": mock.MagicMock()}
    import base64, collections, html, io, json, math, re as _re, time, unicodedata, textwrap
    ns.update(base64=base64, collections=collections, html=html, io=io, json=json, math=math, re=_re, time=time, unicodedata=unicodedata, textwrap=textwrap,
              Counter=collections.Counter)
    ns["st"].cache_data = lambda *a, **k: (lambda f: f) if not (a and callable(a[0])) else a[0]
    ns["st"].cache_resource = ns["st"].cache_data
    ns["st"].session_state = {}
    ns["st"].secrets = {}
    for nm, (i, node) in sorted(need.items(), key=lambda kv: kv[1][0]):
        mod = ast.Module(body=[node], type_ignores=[])
        try:
            exec(compile(mod, APP, "exec"), ns)
        except Exception as e:   # định nghĩa phụ thuộc thứ không cần thiết: bỏ qua, lỗi sẽ lộ ra nếu hàm cần dùng thật sự gọi tới
            ns.setdefault("_skipped", {})[nm] = repr(e)
    return ns
