from research_suite import run_reference_suite
from challenge_engine import staged_hints
from learning_lab import diagnose

def test_reference_suite_runs_and_matches_labels():
    r = run_reference_suite()
    assert r['summary']['total'] >= 10
    assert r['summary']['failed'] == 0
    assert all(x['elapsed_ms'] >= 0 for x in r['records'])

def test_staged_hints_do_not_give_smiles_answer():
    hints = staged_hints('T01','constitution')
    assert len(hints) == 3
    assert 'CCO' not in ' '.join(hints)

def test_invalid_valence_is_not_silently_repaired():
    result = diagnose('CC(=O)(O)O', 'CC(=O)O')
    assert result['verdict'] == 'invalid'
    assert result['verification']['category'] == 'valence'

def test_equivalent_smiles_accepted():
    from challenge_engine import evaluate_task
    assert evaluate_task('T01','OCC')['correct']
    assert not evaluate_task('T01','COC')['correct']
