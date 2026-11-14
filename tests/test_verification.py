import json
from pathlib import Path
from chem_verification import verify_smiles, compare_to_target, validate_graph, verify_isomer_candidates
from evaluation import evaluate_cases
import pytest


def test_reference_cases():
    cases = json.loads((Path(__file__).parent/'cases.json').read_text(encoding='utf-8'))
    assert all(r['passed'] for r in evaluate_cases(cases))


def test_valence_atom_location():
    r = verify_smiles('CC(=O)(O)O')
    assert r.status == 'invalid' and r.category == 'valence'
    assert r.atom_indices == [1]


def test_graph_rejects_duplicate_ids():
    with pytest.raises(ValueError):
        validate_graph({'atoms':[{'id':1,'el':'C'},{'id':1,'el':'O'}],'bonds':[]})


def test_graph_rejects_unknown_bond():
    with pytest.raises(ValueError):
        validate_graph({'atoms':[{'id':1,'el':'C'}],'bonds':[[1,2,1]]})


def test_graph_accepts_valid():
    assert validate_graph({'atoms':[{'id':1,'el':'C','h':3},{'id':2,'el':'O','h':1}], 'bonds':[[1,2,1]]})


def test_isomer_duplicates_detected():
    r = verify_isomer_candidates('C2H6O', ['CCO','OCC','COC'])
    assert r['duplicate_constitution'] == 1
    assert r['completeness_verified'] is False


def test_stereochemistry_distinction():
    r = compare_to_target('F[C@H](Cl)Br','F[C@@H](Cl)Br')
    assert r['same_constitution'] is True
    assert r['same_stereochemical_representation'] is False
