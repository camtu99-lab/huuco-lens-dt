"""Bài tập cấu trúc có đáp án kiểm chứng RDKit; không phụ thuộc AI.

Đáp án là dữ liệu bài tập do người biên soạn, không phải kết quả thực nghiệm.
"""
from __future__ import annotations
from datetime import datetime, timezone
from chem_verification import compare_to_target, verify_smiles

TASKS = (
    {'id':'T01','title':'Ethanol: nhận diện cùng cấu tạo','prompt':'Viết SMILES của ethanol (CH₃CH₂OH).','target':'CCO','skill':'nhóm chức','difficulty':'Cơ bản','hint':'Phân tử có hai C nối tiếp và nhóm –OH.'},
    {'id':'T02','title':'Axit axetic: kiểm tra hóa trị','prompt':'Viết SMILES của axit axetic (CH₃COOH).','target':'CC(=O)O','skill':'hóa trị','difficulty':'Cơ bản','hint':'C của nhóm –COOH liên kết đôi với một O và liên kết đơn với O còn lại.'},
    {'id':'T03','title':'Phân biệt ancol và ete','prompt':'Viết SMILES của dimethyl ether (CH₃–O–CH₃), không phải ethanol.','target':'COC','skill':'đồng phân cấu tạo','difficulty':'Cơ bản','hint':'O nằm giữa hai nguyên tử C.'},
    {'id':'T04','title':'Liên kết đôi trong anken','prompt':'Viết SMILES của propene (CH₂=CH–CH₃).','target':'C=CC','skill':'liên kết bội','difficulty':'Cơ bản','hint':'Ba nguyên tử C, có một liên kết đôi ở đầu mạch.'},
    {'id':'T05','title':'Hai nhóm –OH','prompt':'Viết SMILES của ethane-1,2-diol (HO–CH₂–CH₂–OH).','target':'OCCO','skill':'nhóm chức','difficulty':'Vận dụng','hint':'Mỗi đầu của mạch hai C có một nhóm –OH.'},
)

def evaluate_task(task_id: str, answer: str) -> dict:
    task = next((t for t in TASKS if t['id'] == task_id), None)
    if task is None:
        raise ValueError('Mã bài tập không tồn tại.')
    v = verify_smiles(answer)
    if v.status != 'valid':
        return {'correct':False,'category':v.category if v.status == 'invalid' else 'unknown',
                'message':v.message,'verification':v.to_dict()}
    comp = compare_to_target(answer, task['target'])
    if comp['status'] != 'compared':
        return {'correct':False,'category':'unknown','message':'Chưa thể đối chiếu cấu trúc.','verification':v.to_dict()}
    if comp['same_constitution']:
        return {'correct':True,'category':'correct','message':'Đúng cấu tạo theo RDKit. Bài này không chấm cấu hình lập thể.','verification':v.to_dict()}
    if comp['same_formula']:
        category, message = 'constitution', 'Cùng công thức phân tử nhưng khác cách nối nguyên tử. Hãy kiểm tra nhóm chức hoặc vị trí liên kết.'
    else:
        category, message = 'formula', 'Công thức phân tử chưa trùng đáp án bài tập. Kiểm tra số nguyên tử và bậc liên kết.'
    return {'correct':False,'category':category,'message':message,'verification':v.to_dict()}

def make_event(task_id: str, answer: str, result: dict, attempt_no: int) -> dict:
    return {'time_utc':datetime.now(timezone.utc).isoformat(), 'task_id':task_id,
            'attempt':attempt_no, 'answer':answer, 'correct':result['correct'],
            'category':result['category'], 'verification_status':result['verification']['status']}

def summarize(events: list[dict]) -> dict:
    attempted = {e['task_id'] for e in events}
    mastered = {e['task_id'] for e in events if e['correct']}
    return {'tasks_attempted':len(attempted), 'tasks_mastered':len(mastered),
            'total_attempts':len(events), 'incorrect_attempts':sum(not e['correct'] for e in events),
            'tasks_total':len(TASKS)}


def staged_hints(task_id: str, category: str) -> list[str]:
    """Ba mức gợi ý: hướng tư duy -> nguyên tắc -> chỉ dẫn cấu trúc.

    Mức cuối KHÔNG xuất trực tiếp SMILES đáp án.
    """
    task = next((t for t in TASKS if t['id'] == task_id), None)
    if task is None:
        raise ValueError('Mã bài tập không tồn tại.')
    first = {'valence':'Hãy kiểm tra hóa trị quanh từng nguyên tử và số liên kết.',
             'syntax':'Kiểm tra cú pháp: ngoặc, số đóng vòng và ký hiệu nguyên tố.',
             'constitution':'Cùng công thức phân tử chưa chắc cùng chất. Kiểm tra cách nối nguyên tử.',
             'formula':'Đếm lại số nguyên tử từng nguyên tố và số H ngầm.',
             'unknown':'Hãy kiểm tra đầu vào rồi thử lại.'}.get(category,'Đọc lại yêu cầu và đối chiếu nhóm chức.')
    return [first, 'Nhớ rằng RDKit kiểm tra cấu trúc, còn bài tập yêu cầu đúng chất và đúng kiểu liên kết.', task['hint']]
