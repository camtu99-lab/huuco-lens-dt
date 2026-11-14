from learning_lab import diagnose, record_attempt


def test_invalid_valence_has_progressive_hints():
    r = diagnose('CC(=O)(O)O')
    assert r['verdict'] == 'invalid'
    assert r['verification']['category'] == 'valence'
    assert len(r['hints']) == 3
    assert r['verification']['atom_indices'] == [1]


def test_syntax_error_is_not_assumed_to_be_bad_drawing():
    r = diagnose('C1CC')
    assert r['verdict'] == 'invalid'
    assert r['verification']['category'] == 'syntax'


def test_valid_without_target_not_graded_correct():
    r = diagnose('CCO')
    assert r['verdict'] == 'valid_only'


def test_same_molecule_different_smiles():
    assert diagnose('OCC', 'CCO')['verdict'] == 'matches_target'


def test_formula_mismatch():
    assert diagnose('CO', 'CCO')['verdict'] == 'formula_differs'


def test_constitution_mismatch():
    assert diagnose('CCO', 'COC')['verdict'] == 'constitution_differs'


def test_invalid_reference_does_not_grade_student():
    assert diagnose('CCO', 'C1CC')['verdict'] == 'target_unverified'


def test_attempt_record_has_verdict():
    r = diagnose('CCO')
    record = record_attempt('CCO', '', r, 1)
    assert record['attempt'] == 1 and record['verdict'] == 'valid_only'
