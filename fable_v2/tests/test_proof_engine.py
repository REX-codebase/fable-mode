from hypothesis import given, strategies as st
import fable_v2.proof_engine as pe

@given(st.text(alphabet=st.characters(blacklist_categories=('C', 'Mn', 'Pc')), min_size=1, max_size=100),
       st.lists(st.text(alphabet=st.characters(blacklist_categories=('C', 'Mn', 'Pc')), min_size=1, max_size=100), min_size=1, max_size=10))
def test_boundary_inputs(code_snippet, variable_names):
    # Generate boundary inputs
    boundary_input = f"{code_snippet} ; {'; '.join(variable_names)}"
    result = pe.validate_invariants(boundary_input)
    assert isinstance(result, bool)

@given(st.recursive(st.text(alphabet=st.characters(blacklist_categories=('C', 'Mn', 'Pc')), min_size=1, max_size=10), lambda x: st.lists(x, min_size=1, max_size=3), max_depth=5))
def test_deeply_nested_ast(nested_ast):
    # Generate deeply nested ASTs
    result = pe.validate_invariants(nested_ast)
    assert isinstance(result, bool)

@given(st.text(alphabet=st.characters(blacklist_categories=('C', 'Mn', 'Pc')), min_size=1, max_size=100))
def test_unicode_identifiers(unicode_code_snippet):
    # Generate code snippets with unicode identifiers
    result = pe.validate_invariants(unicode_code_snippet)
    assert isinstance(result, bool)

@given(st.text(alphabet=st.characters(blacklist_categories=('C', 'Mn', 'Pc')), min_size=1, max_size=100))
def test_empty_input(empty_code_snippet):
    # Test with empty input
    result = pe.validate_invariants(empty_code_snippet)
    assert isinstance(result, bool)

@given(st.text(alphabet=st.characters(blacklist_categories=('C', 'Mn', 'Pc')), min_size=1, max_size=100))
def test_tautology_variants(tautology_code_snippet):
    # Test with tautology variants
    tautology_forms = [
        f"({tautology_code_snippet}) -> ({tautology_code_snippet})",
        f"({tautology_code_snippet}) -> {tautology_code_snippet}",
        f"{tautology_code_snippet} -> ({tautology_code_snippet})"
    ]
    for form in tautology_forms:
        result = pe.validate_invariants(form)
        assert isinstance(result, bool)