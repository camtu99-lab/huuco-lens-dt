"""Đánh giá có thể chạy lại; chỉ ghi số liệu từ những ca đã thực thi."""
import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from chem_verification import verify_smiles, compare_to_target, verify_isomer_candidates


def evaluate_cases(cases):
    rows = []
    for c in cases:
        t0 = time.perf_counter()
        kind = c.get('kind', 'smiles')
        if kind == 'smiles':
            observed = verify_smiles(c['input']).status
            expected = c['expected_status']
            details = {'observed_status': observed}
            passed = observed == expected
        elif kind == 'equivalence':
            d = compare_to_target(c['input'], c['target'])
            observed = d['same_constitution'] if d['status'] == 'compared' else None
            expected = c['expected_same_constitution']
            details = {'observed_same_constitution': observed}
            passed = observed == expected
        elif kind == 'isomers':
            d = verify_isomer_candidates(c['formula'], c['candidates'])
            expected = c['expected_unique_count']
            observed = d['count'] - d['duplicate_constitution']
            details = {'observed_unique_count': observed, 'all_valid': d['valid'] == d['count'],
                       'all_formula_match': d['formula_matches'] == d['count']}
            passed = observed == expected and details['all_valid'] and details['all_formula_match']
        else:
            raise ValueError(f'Loại ca kiểm thử chưa hỗ trợ: {kind}')
        rows.append({'id': c['id'], 'kind': kind, 'passed': passed, 'expected': expected,
                     'observed': observed, 'elapsed_ms': round((time.perf_counter()-t0)*1000, 3), **details})
    return rows


def save_results(rows, output):
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = {'run_utc': datetime.now(timezone.utc).isoformat(), 'n': len(rows),
               'passed': sum(r['passed'] for r in rows), 'failed': sum(not r['passed'] for r in rows),
               'pass_rate': sum(r['passed'] for r in rows) / len(rows) if rows else None,
               'total_elapsed_ms': round(sum(r['elapsed_ms'] for r in rows), 3),
               'results': rows}
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--cases', default='tests/cases.json')
    p.add_argument('--output', default='results/latest.json')
    args = p.parse_args()
    cases = json.loads(Path(args.cases).read_text(encoding='utf-8'))
    summary = save_results(evaluate_cases(cases), args.output)
    print(json.dumps({k:v for k,v in summary.items() if k != 'results'}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if summary['failed'] == 0 else 1)
