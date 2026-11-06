# Decimal formula subset — handoff

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-accounting\cafe_fin`  
Branch: `codex/cafe-fin-accounting-20261106`  
Commit: intentionally not committed by the formula subagent; parent owns the lane commit.  
Engine version: `cafe-fin-decimal-1`. No dependencies, migrations, shared-file edits, network calls or executable formula evaluation were added.

## Interface

```python
from decimal import Decimal
from cafe_fin.accounting.formulas import (
    FormulaCell, FormulaEngine, FormulaError, LiteralCell, translate_formula,
)

cells = {
    "A1": Decimal("0.10"),
    "A2": Decimal("0.20"),
    "B1": FormulaCell(formula_text="=SUM(A1:A2)", cached_value="99"),
    "C1": LiteralCell("=source text, not a formula"),
}
engine = FormulaEngine(cells.__getitem__, max_range=10_000, max_cost=100_000,
                       max_depth=64, cancelled=lambda: False)
assert engine.evaluate("=B1") == Decimal("0.30")
assert translate_formula("=A1+$B$2", 1, 2) == "=C2+$B$2"
```

`evaluate(formula)` returns `Decimal | str | bool | None`. Resolver values may be Decimal, int, text, bool, None, FormulaCell or LiteralCell. Float/nonfinite/unknown types are rejected. A bare resolver string beginning `=` is an intentional formula and is evaluated recursively. **Wrap source text in LiteralCell**, especially text beginning `=`; only schema/parser-identified formula cells should produce FormulaCell/raw formula strings. An explicit literal is never interpreted as formula, network expression, Python or shell.

The resolver receives canonical uppercase A1 addresses without `$`. It must map them to stable logical row/column IDs in a pinned book/source revision. It must not index the current viewport, sort order, filter result or page cache. Return None only for a known blank cell. Unavailable/deleted/outside-snapshot references must raise FormulaError (a domain-specific stable code is preserved) or KeyError/IndexError (converted to FORMULA_REFERENCE). Never substitute blank for data not loaded. The caller is responsible for snapshot/version consistency and for rejecting stale persisted results.

Each `evaluate()` resets the memo cache, cost and dependencies. `engine.dependencies` is the set of visited canonical addresses. `engine.dependency_graph` has edges keyed by formula-cell address, plus `<formula>` for the root expression. It records executed branches only; IF conditions are always dependencies. Changes to the condition or formula revision must invalidate/recompute the result before using a newly selected branch. Cached scalar values are scoped to one evaluation. One engine instance is not thread-safe.

FormulaCell with raw formula text always recalculates and ignores its cached value/status. Without raw text it raises CACHE_ONLY/MISSING_CACHE or the explicit unsupported/external/circular status code; its cache never becomes an authoritative number. Persist raw formula, source cache, newly calculated result, status, engine version and dependency/source revision separately in the caller. A cache is not evidence of recalculation. Invalid raw formula text is SYNTAX even if a cache exists.

## Supported grammar and coercion

- Case-insensitive functions: SUM, AVERAGE, MIN, MAX, COUNT, IF, ROUND, SUMIF, COUNTIF.
- Decimal literals with dot separator and optional exponent, double-quoted strings with doubled quote escapes, TRUE/FALSE constants, same-sheet A1 references and rectangular ranges. Reversed endpoints are normalized. Single-cell references are accepted as SUMIF/COUNTIF range arguments.
- `+ - * / ^`, unary signs, postfix `%`, string concatenation `&`, comparisons `= <> < <= > >=`, parentheses. Exponentiation associates right; exponentiation precedes unary negation. Exponents must be integral and in [-1000,1000]; 0^0 is rejected.
- Either commas or semicolons separate function parameters, consistently throughout one formula. Decimal commas, array formulas, names, sheet-qualified references, whole-row/column ranges, unions, dates as numbers, implicit intersection and other Excel features are unsupported. The full syntax/function allowlist is checked even inside an unselected IF branch.
- IF is lazy: only the condition and selected branch are evaluated/resolved. IF(condition, value) returns FALSE when its condition is false. A condition must be numeric, boolean or blank; arbitrary text is not coerced.
- Arithmetic treats known blank as zero and bool as 1/0. Numeric-looking text remains text and raises VALUE in arithmetic. Aggregates consistently ignore blank, text and booleans, including direct arguments; COUNT counts only Decimal/int numeric values, including zero. SUM/COUNT with no arguments return zero. MIN/MAX with no numeric values return zero; AVERAGE with no numeric values raises DIV_ZERO.
- Text comparisons use Unicode casefold. Equalities between different nonblank types are false; ordered comparisons between different types raise VALUE. For comparison with blank, blank becomes zero, empty string or false to match the other operand's type. Thus blank=0 and blank="" are true, while 0="" is false.
- ROUND uses Decimal ROUND_HALF_UP, including negative values and negative decimal places; places must be integral in [-50,50]. No automatic money/kg quantization is performed by the engine. The caller must validate final precision, scale and core Money/Amount int64 limits.

Decimal operations run in an isolated 50-significant-digit context independent of caller configuration. Finite inputs/results have at most 50 stored significant digits and an adjusted exponent in [-1000,1000]. Exact addition, subtraction, multiplication and nonnegative powers reject Inexact/overflow rather than silently discard amounts. Division, AVERAGE and negative powers use deterministic Decimal rounding to 50 significant digits; ROUND explicitly quantizes with ties away from zero. Results exceeding the documented numeric bounds fail with PRECISION. This is a bounded Decimal subset, not a claim of unlimited rational arithmetic or Excel compatibility.

### SUMIF / COUNTIF criteria

The first argument is a range; SUMIF's optional third argument must have the same rectangular shape. Omission uses the first range as the summed range. Nonmatching SUMIF sum cells are not resolved. Matching sum cells contribute only numeric values. Criteria may be a scalar literal or cell reference. Supported comparison prefixes are `=`, `<>`, `<`, `>`, `<=`, `>=`.

- Numeric criteria (including a numeric string such as `">=2"`) match actual numeric cells; blank and numeric text are not silently cast. `<>` includes values of other types.
- Text equality/inequality supports case-insensitive `*` (zero or more characters), `?` (one character), and escapes `~*`, `~?`, `~~`. A trailing tilde or tilde before another character is literal. Regular-expression metacharacters have no special meaning.
- Empty text criterion matches both known blank and empty text. `"<>"` matches values other than those two. `"*"` matches text (including empty text), not blank/numbers/booleans. Native TRUE/FALSE criteria match boolean values, whereas quoted `"TRUE"` is text.
- Criterion length is capped at 1024 characters. Wildcard matching is iterative, cancellation-aware and charged for every matching/backtracking step; it cannot bypass the operation budget through expensive regular expressions.

## Reference and structural semantics

References address logical slots independent of viewport. `$` anchors affect copy/fill only: `translate_formula(formula,row_delta,col_delta)` moves relative dimensions and preserves absolute dimensions, strings and whitespace. A translation outside worksheet bounds fails with FORMULA_REFERENCE; it never wraps or silently clamps. Supported worksheet bounds are 1,048,576 rows and 16,384 columns. Translation parses the same allowlist and accepts integer deltas only.

**Insert/delete rewriting is not implemented.** A caller must either retain immutable logical slots (including tombstones, with deleted references becoming explicit errors), or refuse reindexing structural edits when formulas would be affected and return a clear `FORMULA_STRUCTURE_UNSUPPORTED` issue. Do not call copy translation as an insert/delete substitute and do not rebuild logical A1 positions from filtered/sorted rows. Creating new row IDs need not move existing logical slots. Schema column rename can preserve meaning by retaining stable column IDs; reordering logical positions requires an identity-aware future migration. These service/schema guards remain integration responsibilities, not hidden behavior of this evaluator.

## Resource bounds and errors

Default limits: 10,000 cells per rectangular range, 100,000 total charged operations and depth 64. Caller-configured depth must be 1..128; other limits must be positive. Formula length is at most 32,768 characters, text values at most 32,767. A total budget also covers lexing, AST visits, reference resolution, aggregation, exponent cost and wildcard matching; multiple small ranges cannot bypass it. Ranges stream addresses one at a time; no workbook/viewport is materialized. Memo/dependency state is bounded by the operation budget. `cancelled()` is checked with every charge, including parsing and wildcard matching; a true return raises CANCELLED. Run large/scheduled calculations outside the UI/request event loop. Resolver/infrastructure errors other than missing-reference errors are intentionally not disguised as formula data errors.

All evaluator error codes have the `FORMULA_` prefix:

| Suffix | Meaning |
| --- | --- |
| SYNTAX | Invalid formula/quotes/separator mixture/missing operand |
| UNSUPPORTED | Function, name, grammar feature or exponent outside subset |
| EXTERNAL_REFERENCE | Sheet/workbook reference or DDE marker; never followed |
| REFERENCE | Invalid/out-of-bounds/unavailable logical address |
| CIRCULAR | Executed dependency cycle |
| DIV_ZERO | Division by zero or AVERAGE with no numeric values |
| VALUE | Invalid type, nonfinite value, direct range arithmetic/result, invalid coercion |
| ARGUMENTS | Wrong function argument count/type/ROUND places |
| PRECISION | Numeric precision/magnitude or Decimal operation exceeded bounds |
| RANGE_SHAPE | SUMIF ranges do not have equal dimensions |
| RANGE_LIMIT | Individual range contains too many cells |
| DEPTH | Parse/AST/dependency traversal too deep |
| COST | Total operation budget exceeded |
| LIMIT | Formula/text/criterion length exceeded |
| CANCELLED | Caller requested cancellation |
| CACHE_ONLY | Cache exists without recalculable raw formula |
| MISSING_CACHE | Formula envelope has neither raw formula nor cache |

Error messages are safe Vietnamese descriptions, not raw data/path/SQL. A caller can map success to supported_calculated; UNSUPPORTED, EXTERNAL_REFERENCE, CIRCULAR, CACHE_ONLY and MISSING_CACHE map to their corresponding import statuses. Other codes are calculation errors; no failure becomes zero. FormulaError raised by the resolver is preserved.

## Verification

PASS — Python 3.12 environment in this worktree:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/accounting/test_formulas.py -q
# 118 passed
.\.venv\Scripts\python.exe -m ruff check backend/cafe_fin/accounting/formulas.py tests/accounting/test_formulas.py
# All checks passed
```

Tests cover Decimal precision/context isolation, negative rounding, aggregates, blank/text/zero/bool distinctions, numeric/string/wildcard criteria/escapes, single/two-dimensional ranges, lazy branch errors/cycles, memo/dependency edges, cache refusal, explicit literal formula-injection protection, unsafe grammar/external/DDE/function rejection, unavailable references, copy anchors/bounds, cancellation and resource limits. The evaluator is tested independently of UI cache. No million-row benchmark, full Excel differential suite or service persistence test is claimed here; those remain lane-level work. This handoff does not claim production readiness.

PASS — additional local smoke probe: 10,000 deterministically generated valid/malformed expressions (seed 20261106, bounded cost) completed with a supported result or FormulaError, without uncaught parser/type/index exceptions. `git diff --check` passed. Runtime: Python 3.12.16.
