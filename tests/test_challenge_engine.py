from challenge_engine import TASKS, evaluate_task, summarize

def test_curated_answers_valid():
    for task in TASKS:
        assert evaluate_task(task['id'], task['target'])['correct'], task['id']

def test_equivalent_smiles():
    assert evaluate_task('T01', 'OCC')['correct']

def test_isomer_wrong():
    r = evaluate_task('T01', 'COC')
    assert not r['correct'] and r['category'] == 'constitution'

def test_valence_wrong():
    r = evaluate_task('T02', 'CC(=O)(O)O')
    assert not r['correct'] and r['category'] == 'valence'

def test_unknown_task():
    import pytest
    with pytest.raises(ValueError):
        evaluate_task('bad', 'CCO')

def test_summary():
    s = summarize([{'task_id':'T01','correct':False},{'task_id':'T01','correct':True},{'task_id':'T02','correct':False}])
    assert s['tasks_attempted'] == 2 and s['tasks_mastered'] == 1 and s['incorrect_attempts'] == 2
