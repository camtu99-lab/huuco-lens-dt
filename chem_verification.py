"""Kiểm chứng có giới hạn bằng RDKit; không dùng Gemini và không cần Streamlit.

Đầu vào SMILES được xem là biểu diễn cấu trúc, không phải bằng chứng về
độ đúng của tên, phản ứng, điều kiện thí nghiệm hay bản vẽ gốc.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Optional
import re
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors

MAX_SMILES_LENGTH = 2000
MAX_ATOMS = 250


@dataclass
class Verification:
    status: str  # valid | invalid | unknown
    category: str  # syntax | valence | aromaticity | structure | limits | none
    message: str
    canonical_smiles: Optional[str] = None
    formula: Optional[str] = None
    atom_indices: list[int] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def verify_smiles(smiles: str) -> Verification:
    s = (smiles or '').strip()
    if not s:
        return Verification('unknown', 'syntax', 'Chưa có SMILES để kiểm chứng.', hints=['Nhập công thức trước khi kiểm tra.'])
    if len(s) > MAX_SMILES_LENGTH:
        return Verification('unknown', 'limits', 'SMILES vượt giới hạn chiều dài xử lý.', hints=['Rút ngắn đầu vào hoặc tách bài toán.'])
    try:
        mol = Chem.MolFromSmiles(s, sanitize=False)
    except Exception:
        mol = None
    if mol is None:
        return Verification('invalid', 'syntax', 'SMILES không phân tích được (cú pháp, ngoặc, vòng hoặc ký hiệu).',
                            hints=['Kiểm tra ngoặc tròn, số đóng vòng và ký hiệu nguyên tố.', 'Thử nhập lại SMILES.'],
                            checked=['phân tích cú pháp SMILES'])
    if mol.GetNumAtoms() > MAX_ATOMS:
        return Verification('unknown', 'limits', 'Cấu trúc vượt giới hạn số nguyên tử.', checked=['phân tích cú pháp SMILES'])
    try:
        Chem.SanitizeMol(mol)
    except Exception as exc:
        indices = []
        if hasattr(exc, 'GetAtomIdx'):
            try:
                indices = [int(exc.GetAtomIdx())]
            except Exception:
                pass
        if not indices:
            match = re.search(r'atom # (\d+)', str(exc))
            if match:
                indices = [int(match.group(1))]
        if isinstance(exc, Chem.AtomValenceException):
            category = 'valence'
            msg = 'RDKit phát hiện hóa trị không được chấp nhận tại nguyên tử trong cấu trúc.'
            hints = ['Đếm tổng bậc liên kết và số H tường minh tại nguyên tử được chỉ ra.',
                     'Kiểm tra điện tích, kiểu liên kết và số nhóm gắn; không tự động xóa nguyên tử.']
        elif isinstance(exc, Chem.KekulizeException):
            category = 'aromaticity'
            msg = 'RDKit không chuẩn hóa được biểu diễn vòng thơm.'
            hints = ['Kiểm tra ký hiệu nguyên tử thơm, liên kết và cách đóng vòng.']
        else:
            category = 'structure'
            msg = 'RDKit không chuẩn hóa được cấu trúc; cần xem xét thêm.'
            hints = ['Kiểm tra liên kết, điện tích và cách biểu diễn phân tử.']
        return Verification('invalid', category, msg, atom_indices=indices, hints=hints,
                            checked=['cú pháp SMILES', 'RDKit sanitization'],
                            limitations=['Lỗi này có thể do biểu diễn SMILES, chưa chứng minh ảnh gốc sai.'])
    try:
        return Verification('valid', 'none', 'SMILES vượt qua kiểm tra cú pháp và chuẩn hóa của RDKit.',
                            canonical_smiles=Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True),
                            formula=rdMolDescriptors.CalcMolFormula(mol),
                            checked=['cú pháp SMILES', 'RDKit sanitization', 'công thức phân tử', 'chuẩn hóa SMILES'],
                            limitations=['Không xác nhận SMILES trùng với ảnh gốc hoặc đáp án đề bài.',
                                         'Không xác nhận tên, tính chất, phản ứng hay tính khả thi tổng hợp.'])
    except Exception:
        return Verification('unknown', 'structure', 'Không hoàn tất được bước tính thông tin phân tử.')


def compare_to_target(candidate: str, target: str) -> dict:
    a, b = verify_smiles(candidate), verify_smiles(target)
    if a.status != 'valid' or b.status != 'valid':
        return {'status': 'unknown', 'message': 'Chưa thể đối chiếu: có cấu trúc không hợp lệ.', 'candidate': a.to_dict(), 'target': b.to_dict()}
    ma, mb = Chem.MolFromSmiles(a.canonical_smiles), Chem.MolFromSmiles(b.canonical_smiles)
    same_constitution = (Chem.MolToSmiles(ma, isomericSmiles=False) == Chem.MolToSmiles(mb, isomericSmiles=False))
    same_stereo = a.canonical_smiles == b.canonical_smiles
    return {'status': 'compared', 'same_formula': a.formula == b.formula,
            'same_constitution': same_constitution, 'same_stereochemical_representation': same_stereo,
            'message': 'Đối chiếu theo biểu diễn phân tử, không đánh giá cách viết tay.'}


def verify_ai_proposal(proposal: dict) -> dict:
    """Bổ sung kết quả độc lập; KHÔNG đánh dấu mọi trường AI sinh là đã xác minh."""
    result = dict(proposal or {})
    result['kiem_chung_rdkit'] = verify_smiles(result.get('smiles', '')).to_dict()
    return result


def validate_graph(graph: dict) -> dict:
    """Kiểm tra cấu trúc JSON AI chép trước khi chuyển thành SMILES."""
    if not isinstance(graph, dict):
        raise ValueError('Đồ thị AI trả về không phải đối tượng JSON.')
    atoms, bonds = graph.get('atoms'), graph.get('bonds')
    if not isinstance(atoms, list) or not atoms or not isinstance(bonds, list):
        raise ValueError('Thiếu danh sách atoms hoặc bonds hợp lệ.')
    if len(atoms) > MAX_ATOMS or len(bonds) > 4 * MAX_ATOMS:
        raise ValueError('Đồ thị vượt giới hạn xử lý.')
    ids = set()
    for a in atoms:
        if not isinstance(a, dict) or type(a.get('id')) is not int or a['id'] in ids:
            raise ValueError('ID nguyên tử không hợp lệ hoặc bị trùng.')
        ids.add(a['id'])
        el = a.get('el')
        if not isinstance(el, str) or not el.isalpha() or len(el) > 2:
            raise ValueError('Ký hiệu nguyên tố không hợp lệ.')
        try:
            if Chem.GetPeriodicTable().GetAtomicNumber(el.capitalize()) == 0:
                raise ValueError('Nguyên tố không được hỗ trợ.')
        except Exception as exc:
            raise ValueError('Nguyên tố không được hỗ trợ.') from exc
        h = a.get('h')
        if h is not None and (type(h) is not int or not 0 <= h <= 20):
            raise ValueError('Số H ghi kèm nguyên tử không hợp lệ.')
    seen = set()
    for b in bonds:
        if not isinstance(b, (list, tuple)) or len(b) != 3:
            raise ValueError('Liên kết phải có dạng [id1,id2,bậc].')
        i, j, order = b
        if type(i) is not int or type(j) is not int or type(order) is not int or i not in ids or j not in ids or i == j or order not in (1, 2, 3):
            raise ValueError('Liên kết chứa ID hoặc bậc không hợp lệ.')
        key = tuple(sorted((i, j)))
        if key in seen:
            raise ValueError('Liên kết bị khai báo lặp.')
        seen.add(key)
    return graph


def verify_isomer_candidates(formula: str, smiles_list: list[str]) -> dict:
    """Kiểm tra từng ứng viên; không chứng minh thuật toán đã liệt kê đầy đủ."""
    from collections import Counter
    seen, records = set(), []
    for s in smiles_list:
        v = verify_smiles(s)
        matches = v.status == 'valid' and v.formula == formula
        key = None
        if v.status == 'valid':
            mol = Chem.MolFromSmiles(v.canonical_smiles)
            key = Chem.MolToSmiles(mol, isomericSmiles=False)
        duplicate = key in seen if key else False
        if key:
            seen.add(key)
        records.append({'smiles': s, 'status': v.status, 'formula_matches': matches, 'duplicate_constitution': duplicate})
    c = Counter(r['status'] for r in records)
    return {'count': len(records), 'valid': c['valid'], 'invalid': c['invalid'], 'unknown': c['unknown'],
            'formula_matches': sum(r['formula_matches'] for r in records),
            'duplicate_constitution': sum(r['duplicate_constitution'] for r in records),
            'completeness_verified': False, 'records': records}
