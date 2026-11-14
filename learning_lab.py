"""Bài thực hành kiểm chứng và tự sửa cấu trúc: RDKit, không cần Gemini.

Không đồng nhất SMILES hợp lệ với đáp án đúng; không tự suy đoán sửa chữa.
"""
from __future__ import annotations
from datetime import datetime, timezone
from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D
from chem_verification import verify_smiles, compare_to_target


def diagnose(student: str, target: str = '') -> dict:
    v = verify_smiles(student)
    out = {'verification': v.to_dict(), 'comparison': None, 'verdict': 'unknown', 'hints': [], 'highlight_svg': None}
    if v.status == 'invalid':
        out['verdict'] = 'invalid'
        if v.category == 'valence':
            out['hints'] = [
                'Hãy đếm số liên kết quanh từng nguyên tử, nhất là vị trí được đánh dấu.',
                'Đối với C trung hòa thông thường, tổng bậc liên kết là 4. Kiểm tra số liên kết đơn, đôi, ba và điện tích.',
                'Xem lại các nhánh và liên kết ở vị trí nghi vấn; tự sửa SMILES rồi nhấn “Kiểm tra lại”. Không có phép sửa duy nhất nếu chưa biết đề bài.'
            ]
        elif v.category == 'syntax':
            out['hints'] = ['Kiểm tra các cặp ngoặc và ký hiệu nguyên tố.', 'Kiểm tra số đóng vòng và dấu liên kết.', 'Sửa cách viết SMILES, rồi thử lại. Chưa thể kết luận bài vẽ hóa học ban đầu sai.']
        else:
            out['hints'] = ['Kiểm tra loại liên kết và điện tích.', 'Xem lại các nguyên tử vòng hoặc nguyên tử thơm nếu có.', 'Sửa biểu diễn và kiểm tra lại; trường hợp này có thể cần giáo viên đánh giá.']
        out['highlight_svg'] = draw_problem(student, v.atom_indices)
    elif v.status == 'unknown':
        out['hints'] = ['Kiểm tra đầu vào hoặc giới hạn xử lý.', 'Thử một cấu trúc ngắn hơn.', 'Nếu vẫn không thể xác minh, nhờ giáo viên đối chiếu.']
    elif target and target.strip():
        comp = compare_to_target(student, target)
        out['comparison'] = comp
        if comp['status'] == 'compared':
            if comp['same_stereochemical_representation']:
                out['verdict'] = 'matches_target'
                out['hints'] = ['Cấu trúc trùng với cấu trúc tham chiếu theo biểu diễn lập thể của RDKit.']
            elif comp['same_constitution']:
                out['verdict'] = 'stereo_differs'
                out['hints'] = ['Kiểm tra ký hiệu @, @@, / và \\ nếu đề yêu cầu cấu hình lập thể.', 'Hai cấu trúc có cùng cách nối nguyên tử nhưng biểu diễn lập thể khác nhau.', 'Nếu bài chỉ yêu cầu đồng phân cấu tạo, khác biệt này có thể không ảnh hưởng đến đáp án.']
            elif comp['same_formula']:
                out['verdict'] = 'constitution_differs'
                out['hints'] = ['Công thức phân tử trùng nhưng cách nối nguyên tử khác.', 'Đối chiếu vị trí nhánh, liên kết đôi và nhóm chức với yêu cầu đề bài.', 'Vẽ lại từng liên kết rồi nhập cấu trúc đã sửa để thử lại.']
            else:
                out['verdict'] = 'formula_differs'
                out['hints'] = ['Đếm lại số nguyên tử C, H, O và các nguyên tố khác.', 'Đối chiếu công thức phân tử với đề bài.', 'Kiểm tra số nhánh, nhóm chức và số H ngầm trước khi thử lại.']
        else:
            out['verdict'] = 'target_unverified'
            out['hints'] = ['Cấu trúc học sinh hợp lệ, nhưng cấu trúc tham chiếu không kiểm chứng được.', 'Kiểm tra lại đáp án tham chiếu trước khi chấm.']
    elif v.status == 'valid':
        out['verdict'] = 'valid_only'
        out['hints'] = ['SMILES qua kiểm tra RDKit, nhưng chưa chứng minh đáp án đúng yêu cầu bài.', 'Nếu có đáp án tham chiếu, nhập vào ô dành cho giáo viên để so sánh.', 'Đối chiếu nhóm chức, vị trí liên kết và điều kiện của đề bài.']
    return out


def draw_problem(smiles: str, indices: list[int]) -> str | None:
    if not indices:
        return None
    try:
        mol = Chem.MolFromSmiles(smiles, sanitize=False)
        if mol is None or mol.GetNumAtoms() > 100:
            return None
        Chem.rdDepictor.Compute2DCoords(mol)
        d = rdMolDraw2D.MolDraw2DSVG(640, 360)
        d.DrawMolecule(mol, highlightAtoms=[i for i in indices if 0 <= i < mol.GetNumAtoms()])
        d.FinishDrawing()
        return d.GetDrawingText()
    except Exception:
        return None


def record_attempt(student: str, target: str, result: dict, number: int) -> dict:
    return {'attempt': number, 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
            'student_smiles': student, 'target_smiles': target,
            'verdict': result['verdict'], 'verification_status': result['verification']['status'],
            'error_category': result['verification']['category']}
