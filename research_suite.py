"""Bộ đánh giá có thể chạy lại. Các ca do người biên soạn, KHÔNG phải dữ liệu ảnh thực."""
from __future__ import annotations
import json, time, platform
from datetime import datetime, timezone
from pathlib import Path
from rdkit import rdBase
from chem_verification import verify_smiles, compare_to_target, verify_isomer_candidates

CASES = (
 {'id':'S01','group':'valid','smiles':'CCO','expected':'valid'},
 {'id':'S02','group':'valid','smiles':'CC(=O)O','expected':'valid'},
 {'id':'S03','group':'valid','smiles':'c1ccccc1','expected':'valid'},
 {'id':'S04','group':'valence','smiles':'CC(=O)(O)O','expected':'invalid'},
 {'id':'S05','group':'valence','smiles':'C(C)(C)(C)(C)C','expected':'invalid'},
 {'id':'S06','group':'syntax','smiles':'C1CC','expected':'invalid'},
 {'id':'S07','group':'syntax','smiles':'C(','expected':'invalid'},
 {'id':'S08','group':'valid','smiles':'OCC','expected':'valid'},
 {'id':'P01','group':'equivalent','smiles':'OCC','target':'CCO','expected':'same'},
 {'id':'P02','group':'isomer','smiles':'COC','target':'CCO','expected':'different'},
 {'id':'P03','group':'isomer','smiles':'CCO','target':'CC(=O)O','expected':'different'},
)

def run_reference_suite(cases=CASES):
    rows=[]
    for case in cases:
        t=time.perf_counter()
        if 'target' in case:
            comp=compare_to_target(case['smiles'],case['target'])
            actual=('same' if comp['status']=='compared' and comp['same_constitution'] else
                    'different' if comp['status']=='compared' else 'unknown')
        else:
            actual=verify_smiles(case['smiles']).status
        rows.append({'id':case['id'],'group':case['group'],'input':case['smiles'],
                     'expected':case['expected'],'actual':actual,'pass':actual==case['expected'],
                     'elapsed_ms':round((time.perf_counter()-t)*1000,3)})
    return {'metadata':{'created_utc':datetime.now(timezone.utc).isoformat(),
                        'dataset':'hand-authored reference cases, not independent field data',
                        'rdkit_version':rdBase.rdkitVersion,'python':platform.python_version(),
                        'scope':'SMILES validity and constitutional comparison only'},
            'summary':{'total':len(rows),'passed':sum(r['pass'] for r in rows),
                       'failed':sum(not r['pass'] for r in rows),
                       'mean_elapsed_ms':round(sum(r['elapsed_ms'] for r in rows)/len(rows),3) if rows else 0},
            'records':rows}

def save_suite(path):
    result=run_reference_suite()
    target=Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='results/research_suite_latest.json')
    args=parser.parse_args()
    result=save_suite(args.output)
    print(json.dumps(result['summary'],ensure_ascii=False))
    raise SystemExit(0 if result['summary']['failed']==0 else 1)
