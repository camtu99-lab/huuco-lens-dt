"""Bài tập đọc công thức cấu tạo trực quan, chấm bằng RDKit, không cần API."""
from __future__ import annotations
from io import BytesIO
from datetime import datetime, timezone
from rdkit import Chem
from rdkit.Chem import Draw
from chem_verification import compare_to_target

QUESTIONS = (
    {'id':'H01','title':'Tìm đúng ethanol','question':'Chất nào là ethanol (ancol etylic), có nhóm –OH?',
     'choices':(('A','CCO'),('B','COC'),('C','CC=O')),'target':'CCO',
     'explain':'Ethanol có mạch hai carbon và nhóm –OH. CH₃–O–CH₃ là ete: cùng công thức phân tử nhưng khác cách nối nguyên tử.',
     'hint':'Hãy tìm nhóm –OH gắn trực tiếp với nguyên tử carbon.'},
    {'id':'H02','title':'Phân biệt ancol và ete','question':'Chất nào là đimetyl ete (CH₃–O–CH₃)?',
     'choices':(('A','CCO'),('B','COC'),('C','CC(=O)O')),'target':'COC',
     'explain':'Đimetyl ete có oxygen nằm giữa hai nhóm CH₃. Ethanol có oxygen ở đầu mạch, thuộc nhóm ancol.',
     'hint':'Tìm cấu trúc có nguyên tử O nối với hai nguyên tử C.'},
    {'id':'H03','title':'Nhận biết axit cacboxylic','question':'Công thức nào biểu diễn axit axetic (CH₃COOH)?',
     'choices':(('A','CC(=O)O'),('B','CCO'),('C','CC=O')),'target':'CC(=O)O',
     'explain':'Nhóm –COOH có carbon liên kết đôi với một O và liên kết đơn với một nhóm –OH.',
     'hint':'Tìm nhóm gồm C=O và –OH cùng gắn trên một carbon.'},
    {'id':'H04','title':'Tìm liên kết đôi','question':'Chất nào là propen (CH₂=CH–CH₃)?',
     'choices':(('A','CCC'),('B','C=CC'),('C','C#CC')),'target':'C=CC',
     'explain':'Propen có ba nguyên tử carbon và một liên kết đôi C=C. Propan chỉ có liên kết đơn; propin có liên kết ba.',
     'hint':'Đếm ba nguyên tử C rồi tìm đúng một liên kết đôi.'},
    {'id':'H05','title':'Tìm hai nhóm hydroxyl','question':'Cấu trúc nào là etan-1,2-điol (HO–CH₂–CH₂–OH)?',
     'choices':(('A','CCO'),('B','OCCO'),('C','COC')),'target':'OCCO',
     'explain':'Etan-1,2-điol có hai nguyên tử C và hai nhóm –OH, mỗi nhóm nằm ở một đầu mạch.',
     'hint':'Tìm phân tử có hai nhóm –OH ở hai đầu của mạch carbon.'},
)

def image_for(smiles: str) -> bytes:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError('Cấu trúc mẫu không hợp lệ')
    img = Draw.MolToImage(mol, size=(480, 270), kekulize=True)
    buf = BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()

def grade(question_id: str, choice: str) -> dict:
    q = next((q for q in QUESTIONS if q['id'] == question_id), None)
    if q is None:
        raise ValueError('Bài tập không tồn tại')
    options = dict(q['choices'])
    if choice not in options:
        raise ValueError('Lựa chọn không tồn tại')
    comp = compare_to_target(options[choice], q['target'])
    if comp.get('status') != 'compared':
        return {'correct':False,'verified':False,'message':'Chưa kiểm chứng được; không chấm bài.'}
    return {'correct':bool(comp['same_constitution']),'verified':True,
            'message':('Đúng rồi! ' if comp['same_constitution'] else 'Chưa đúng. ') + q['explain']}

def event(question_id: str, choice: str, outcome: dict) -> dict:
    return {'time_utc':datetime.now(timezone.utc).isoformat(), 'question_id':question_id,
            'choice':choice,'correct':outcome['correct'],'verified':outcome['verified']}
