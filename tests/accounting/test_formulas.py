from decimal import ROUND_DOWN, Decimal, Inexact, localcontext

import pytest
from cafe_fin.accounting.formulas import (
    ENGINE_VERSION,
    FormulaCell,
    FormulaEngine,
    FormulaError,
    LiteralCell,
    translate_formula,
)


def engine(cells=None, **limits):
    # An absent key is an unavailable reference, not an empty cell.
    return FormulaEngine((cells or {}).__getitem__, **limits)


def assert_error(code, expression, cells=None, **limits):
    with pytest.raises(FormulaError) as failure:
        engine(cells, **limits).evaluate(expression)
    assert failure.value.code == "FORMULA_" + code
    assert failure.value.message


@pytest.mark.parametrize(("expression", "expected"), [
    ("=0.1+0.2", Decimal("0.3")),
    ("=999999999999999999.99+0.01", Decimal("1000000000000000000.00")),
    ("=2+3*4", Decimal(14)),
    ("=(2+3)*4", Decimal(20)),
    ("=-2^2", Decimal(-4)),
    ("=2^3^2", Decimal(512)),
    ("=2^-3", Decimal("0.125")),
    ("=50%", Decimal("0.5")),
    ("=--1", Decimal(1)),
    ("=1e-3+.002", Decimal("0.003")),
    ("=1/8", Decimal("0.125")),
    ("=TRUE+2", Decimal(3)),
    ("=ROUND(-1.005,2)", Decimal("-1.01")),
    ("=ROUND(1.005;2)", Decimal("1.01")),
    ("=ROUND(-125,-1)", Decimal(-130)),
    ("=ROUND(125,-1)", Decimal(130)),
    ("=SUM()", Decimal(0)),
    ("=COUNT()", Decimal(0)),
    ("=MIN(4,-2,0)", Decimal(-2)),
    ("=MAX(4,-2,0)", Decimal(4)),
    ("=AVERAGE(1,2)", Decimal("1.5")),
    ('="A"&"""b"', 'A"b'),
    ('="A"="a"', True),
    ('="a"<>"B"', True),
    ("=2>=1", True),
    ("=1<=2", True),
    ('=1="1"', False),
    ("=IF(FALSE,1)", False),
    ("=IF(TRUE,1,1/0)", Decimal(1)),
    ("=IF(FALSE,1/0,2)", Decimal(2)),
])
def test_arithmetic_and_functions(expression, expected):
    assert engine().evaluate(expression) == expected


def test_precision_and_rounding_independent_of_callers_decimal_context():
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        assert engine().evaluate("=123456789.12+0.03") == Decimal("123456789.15")
        result = engine().evaluate("=1/3")
        assert result == Decimal("0." + "3" * 50)
        assert engine().evaluate("=ROUND(-1.005,2)") == Decimal("-1.01")
        assert context.prec == 2
        assert context.traps[Inexact] is True


@pytest.mark.parametrize("function,expected", [
    ("SUM", Decimal("2.5")),
    ("AVERAGE", Decimal("1.25")),
    ("COUNT", Decimal(2)),
    ("MIN", Decimal(0)),
    ("MAX", Decimal("2.5")),
])
def test_blank_text_zero_boolean_and_decimal_are_distinct(function, expected):
    cells = {"A1": None, "A2": "", "A3": "12", "A4": Decimal(0),
             "A5": Decimal("2.5"), "A6": True}
    assert engine(cells).evaluate(f"={function}(A1:A6)") == expected


def test_direct_aggregate_arguments_use_same_numeric_rules_as_ranges():
    assert engine().evaluate('=COUNT("2",TRUE,0)') == Decimal(1)
    assert engine().evaluate('=SUM("2",TRUE,0)') == Decimal(0)
    assert engine({"A1": None}).evaluate("=A1+2") == Decimal(2)
    assert engine({"A1": None}).evaluate('=A1=""') is True
    assert engine({"A1": None}).evaluate("=A1=0") is True
    assert engine({"A1": None}).evaluate("=IF(A1,1,2)") == Decimal(2)
    assert_error("VALUE", "=A1+2", {"A1": "2"})
    assert_error("DIV_ZERO", '=AVERAGE("2",TRUE)')
    assert engine().evaluate('=MIN("")') == Decimal(0)


def test_recursive_references_are_memoized_and_graph_retains_every_edge():
    cells = {"A1": "=B1+C1", "B1": "=D1*2", "C1": "=D1+1", "D1": Decimal("0.10")}
    calls = []

    def resolve(reference):
        calls.append(reference)
        return cells[reference]

    calculator = FormulaEngine(resolve)
    assert calculator.evaluate("=$A$1+A1") == Decimal("2.60")
    assert calls == ["A1", "B1", "D1", "C1"]
    assert calculator.dependencies == set(cells)
    assert calculator.dependency_graph == {
        "<formula>": {"A1"}, "A1": {"B1", "C1"}, "B1": {"D1"}, "C1": {"D1"},
    }
    cells["D1"] = Decimal("0.20")
    assert calculator.evaluate("=A1") == Decimal("1.60")


def test_lazy_if_does_not_resolve_other_branch_and_can_skip_cycle():
    cells = {"A1": "=IF(TRUE,2,A1)", "A2": "=IF(FALSE,A2,3)"}
    calculator = engine(cells)
    assert calculator.evaluate("=A1+A2") == Decimal(5)
    assert calculator.dependencies == {"A1", "A2"}
    assert calculator.evaluate("=IF(TRUE,5,Z99)") == Decimal(5)


def test_cycle_and_depth_are_separate_failures():
    assert_error("CIRCULAR", "=A1", {"A1": "=B1", "B1": "=A1"})
    assert_error("CIRCULAR", "=A1", {"A1": "=SUM(A1:A2)", "A2": 1})
    assert_error("DEPTH", "=" + "(" * 65 + "1" + ")" * 65)
    cells = {f"A{row}": f"=A{row + 1}" for row in range(1, 100)}
    assert_error("DEPTH", "=A1", cells)
    assert_error("DEPTH", "=" + "+".join(["1"] * 100))


def test_range_resolution_is_logical_and_not_bound_to_display_order():
    logical = {"A1": Decimal("10.25"), "A2": Decimal("20.25"), "A3": Decimal("30.25")}
    display_order = ["A3", "A1", "A2"]
    calculator = engine(logical)
    assert calculator.evaluate("=SUM(A1:A3)") == Decimal("60.75")
    display_order.reverse()
    assert calculator.evaluate("=A1-A2") == Decimal(-10)
    assert calculator.evaluate("=SUM(A3:A1)") == Decimal("60.75")


def test_two_dimensional_ranges_are_row_major_and_support_int_resolver_values():
    cells = {"A1": 1, "B1": 2, "A2": 3, "B2": 4}
    calls = []

    def resolve(reference):
        calls.append(reference)
        return cells[reference]

    assert FormulaEngine(resolve).evaluate("=SUM($A$1:B2)") == Decimal(10)
    assert calls == ["A1", "B1", "A2", "B2"]


@pytest.mark.parametrize("criterion,expected", [
    ('"a*"', 4), ('"A?"', 3), ('"a~*"', 1), ('"a~?"', 1),
    ('"a~~"', 1), ('"a~"', 1), ('"<>a*"', 6), ('""', 2),
    ('"<>"', 8), ('"*"', 6), ('0', 1), ('">=2"', 1),
    ('"2"', 1), ('TRUE', 1),
])
def test_countif_numeric_blank_text_wildcards_and_escapes(criterion, expected):
    cells = {"A1": "abc", "A2": "a*", "A3": "a?", "A4": "a~", "A5": None,
             "A6": "", "A7": Decimal(0), "A8": Decimal(2), "A9": "2", "A10": True}
    assert engine(cells).evaluate(f"=COUNTIF(A1:A10,{criterion})") == Decimal(expected)


def test_sumif_matches_same_shape_and_does_not_resolve_nonmatching_sum_cells():
    cells = {"A1": "Coffee", "A2": "Tea", "A3": "coffee", "B1": Decimal("0.1"),
             "B2": "=1/0", "B3": Decimal("0.2")}
    calculator = engine(cells)
    assert calculator.evaluate('=SUMIF(A1:A3,"COFFEE",B1:B3)') == Decimal("0.3")
    assert "B2" not in calculator.dependencies
    assert engine({"A1": 0, "A2": 1, "A3": 2}).evaluate('=SUMIF(A1:A3,">0")') == Decimal(3)
    assert_error("RANGE_SHAPE", '=SUMIF(A1:A3,"x",B1:B2)', cells)
    assert_error("ARGUMENTS", '=SUMIF(1,"x")')


def test_sumif_countif_accept_single_cell_ranges_and_scalar_reference_criteria():
    cells = {"A1": "Coffee", "B1": Decimal("12.50"), "C1": "c*"}
    assert engine(cells).evaluate("=COUNTIF(A1,C1)") == Decimal(1)
    assert engine(cells).evaluate("=SUMIF(A1,C1,B1)") == Decimal("12.50")
    assert engine(cells).evaluate('=SUMIF(B1,">0")') == Decimal("12.50")


def test_wildcard_matching_handles_empty_and_escape_sequences_without_regex_execution():
    cells = {"A1": "a.b", "A2": "a+b", "A3": "[a]", "A4": "VIỆT NAM", "A5": ""}
    assert engine(cells).evaluate('=COUNTIF(A1:A5,"a.b")') == Decimal(1)
    assert engine(cells).evaluate('=COUNTIF(A1:A5,"việt*")') == Decimal(1)
    assert engine(cells).evaluate('=COUNTIF(A1:A5,"*")') == Decimal(5)


def test_formula_cell_recalculates_and_never_uses_cache_as_authoritative():
    assert ENGINE_VERSION == "cafe-fin-decimal-1"
    cells = {"A1": FormulaCell("=0.1+0.2", "999", "cache_only")}
    assert engine(cells).evaluate("=A1") == Decimal("0.3")
    assert_error("CACHE_ONLY", "=A1", {"A1": FormulaCell(cached_value=Decimal(99))})
    assert_error("MISSING_CACHE", "=A1", {"A1": FormulaCell()})
    assert_error("UNSUPPORTED", "=A1", {"A1": FormulaCell("=NOW()", Decimal(99))})
    assert_error("EXTERNAL_REFERENCE", "=A1", {"A1": FormulaCell("=[book]Sheet!A1", Decimal(99))})
    assert_error("UNSUPPORTED", "=A1", {"A1": FormulaCell(calculation_status="unsupported")})
    assert_error("SYNTAX", "=A1", {"A1": FormulaCell("12", Decimal(99))})


def test_untrusted_text_is_explicit_literal_and_never_executed_as_formula():
    raw = '=WEBSERVICE("https://invalid.example")'
    cells = {"A1": LiteralCell(raw), "A2": LiteralCell("=1/0")}
    assert engine(cells).evaluate("=A1") == raw
    assert engine(cells).evaluate("=SUM(A1:A2)") == Decimal(0)
    assert engine(cells).evaluate('=A2&" text"') == "=1/0 text"


@pytest.mark.parametrize("expression,code", [
    ("=1/0", "DIV_ZERO"), ("=0^-1", "DIV_ZERO"), ("=0^0", "VALUE"),
    ("=4^0.5", "UNSUPPORTED"), ("=2^1001", "UNSUPPORTED"),
    ("=1e1001", "PRECISION"), ("=1e50+1e-50", "PRECISION"),
    ("=ROUND(1,2.5)", "ARGUMENTS"), ("=ROUND(1,51)", "ARGUMENTS"),
    ("=ROUND(1)", "ARGUMENTS"), ("=IF(1)", "ARGUMENTS"),
    ('=IF("true",1,2)', "VALUE"), ("=IF(TRUE,A1:A2,2)", "VALUE"),
    ("=SUMIF(A1:A2)", "ARGUMENTS"), ("=COUNTIF(A1:A2,1,2)", "ARGUMENTS"),
    ("=A0", "REFERENCE"), ("=XFE1", "REFERENCE"),
    ("=A1048577", "REFERENCE"), ("=A999999999999999999999", "REFERENCE"),
    ("=A1", "REFERENCE"), ("=A:A", "UNSUPPORTED"),
    ("=A1:A2", "VALUE"), ("=A1:A2+1", "VALUE"),
    ("=SUM(1;2,3)", "SYNTAX"), ("SUM(1)", "SYNTAX"),
    ("=", "SYNTAX"), ("=1+", "SYNTAX"), ("=SUM(1,)", "SYNTAX"),
    ('="bad', "SYNTAX"), ("=1 2", "SYNTAX"),
    ("=NOW()", "UNSUPPORTED"), ("=WEBSERVICE(1)", "UNSUPPORTED"),
    ("=__import__(1)", "UNSUPPORTED"), ("=A1.__class__", "UNSUPPORTED"),
    ("=[file.xlsx]Sheet1!A1", "EXTERNAL_REFERENCE"),
    ("=Sheet1!A1", "EXTERNAL_REFERENCE"),
    ("='Sheet name'!A1", "EXTERNAL_REFERENCE"),
    ("=cmd|' /C calc'!A0", "EXTERNAL_REFERENCE"),
])
def test_stable_errors_and_allowlist_reject_unsafe_or_unsupported_expressions(expression, code):
    assert_error(code, expression)


@pytest.mark.parametrize("value", [1.25, float("inf"), Decimal("NaN"), Decimal("Infinity"), [], {}])
def test_resolver_rejects_floats_non_finite_and_other_implicit_coercions(value):
    assert_error("VALUE", "=A1", {"A1": value})


def test_unavailable_reference_error_can_be_preserved_by_resolver():
    def missing(_):
        raise FormulaError("FORMULA_OUTSIDE_SNAPSHOT", "Ô nằm ngoài snapshot nhập.")
    with pytest.raises(FormulaError) as failure:
        FormulaEngine(missing).evaluate("=A1")
    assert failure.value.code == "FORMULA_OUTSIDE_SNAPSHOT"


def test_range_cost_depth_size_and_text_limits_are_enforced_before_unbounded_work():
    assert_error("RANGE_LIMIT", "=SUM(A1:A10001)")
    assert_error("COST", "=SUM(A1:A3)", {"A1": 1, "A2": 2, "A3": 3}, max_cost=12)
    assert_error("LIMIT", "=" + "1" * 32768)
    assert_error("LIMIT", "=A1", {"A1": "x" * 32768})
    assert_error("LIMIT", '=COUNTIF(A1:A1,"' + "*" * 1025 + '")')
    calculator = engine({"A1": "a" * 1000}, max_cost=300)
    with pytest.raises(FormulaError) as failure:
        calculator.evaluate('=COUNTIF(A1:A1,"*a*a*a*a*b")')
    assert failure.value.code == "FORMULA_COST"


def test_cancellation_interrupts_range_and_wildcard_processing():
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls > 50

    assert_error("CANCELLED", "=SUM(A1:A1000)", {f"A{i}": 1 for i in range(1, 1001)}, cancelled=cancelled)
    assert calls == 51
    assert_error("CANCELLED", "=1", cancelled=lambda: True)


@pytest.mark.parametrize(("formula", "row_delta", "col_delta", "expected"), [
    ("=A1+$A1+A$1+$A$1", 2, 3, "=D3+$A3+D$1+$A$1"),
    ("=SUM(A1:$B$4)", 1, 1, "=SUM(B2:$B$4)"),
    ('=IF(A1="A1", """B2", B2)', 1, 2, '=IF(C2="A1", """B2", D3)'),
    ("= Z9 + AA10 ", -8, -25, "= A1 + B2 "),
    ("=$XFD$1048576", 1000000000, -1000000000, "=$XFD$1048576"),
])
def test_copy_fill_translation_preserves_each_anchor_strings_and_whitespace(formula, row_delta, col_delta, expected):
    assert translate_formula(formula, row_delta, col_delta) == expected


@pytest.mark.parametrize("formula,row_delta,col_delta", [
    ("=A1", -1, 0), ("=A1", 0, -1), ("=XFD1", 0, 1), ("=A1048576", 1, 0),
])
def test_translation_rejects_reference_out_of_bounds(formula, row_delta, col_delta):
    with pytest.raises(FormulaError) as failure:
        translate_formula(formula, row_delta, col_delta)
    assert failure.value.code == "FORMULA_REFERENCE"


def test_engine_limits_validate_configuration():
    for limits in ({"max_range": 0}, {"max_cost": 0}, {"max_depth": 0}, {"max_depth": 129}):
        with pytest.raises(ValueError):
            engine(**limits)
