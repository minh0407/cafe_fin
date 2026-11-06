"""Bounded, local formula subset with Decimal results and no executable expressions.

The resolver must address immutable logical A1 positions in a pinned book revision,
never indexes in a filtered/sorted viewport. Missing/unavailable cells must raise
FormulaError; only a known empty cell may return None. See the lane handoff for
coercion, precision, cache and structural-edit semantics.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from decimal import (
    ROUND_HALF_UP,
    Decimal,
    DecimalException,
    Inexact,
    InvalidOperation,
    Overflow,
    localcontext,
)

Scalar = Decimal | str | bool | None
ENGINE_VERSION = "cafe-fin-decimal-1"
DECIMAL_PRECISION = 50
MAX_ROW = 1_048_576
MAX_COLUMN = 16_384
MAX_TEXT = 32_767
MAX_FORMULA = 32_768
FUNCTIONS = frozenset({"SUM", "AVERAGE", "MIN", "MAX", "COUNT", "IF", "ROUND", "SUMIF", "COUNTIF"})
_NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_WORD = re.compile(r"\$?[A-Za-z_][A-Za-z0-9_.$]*")
_REF = re.compile(r"(\$?)([A-Za-z]+)(\$?)([0-9]+)\Z")
_NUMERIC_CRITERION = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


class FormulaError(ValueError):
    """A stable public code with a non-sensitive, user-facing message."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _fail(code: str, message: str) -> None:
    raise FormulaError("FORMULA_" + code, message)


@dataclass(frozen=True)
class LiteralCell:
    """Explicit literal, including untrusted text that happens to start with =."""

    value: object


@dataclass(frozen=True)
class FormulaCell:
    """Imported formula/cache envelope. Cached values are never authoritative.

    If raw formula text is present it is recalculated. If it is unavailable,
    cached_value only distinguishes CACHE_ONLY from MISSING_CACHE.
    """

    formula_text: str | None = None
    cached_value: object = None
    calculation_status: str | None = None


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    start: int
    end: int


@dataclass(frozen=True)
class _Node:
    kind: str
    value: object = None
    children: tuple[_Node, ...] = ()


def _coordinates(reference: str) -> tuple[int, int, bool, bool]:
    match = _REF.fullmatch(reference)
    if not match:
        _fail("REFERENCE", "Tham chiếu ô không hợp lệ.")
    assert match is not None
    absolute_column, letters, absolute_row, row_text = match.groups()
    # Bound parsing before converting enormous integers or column labels.
    if len(letters) > 3 or len(row_text) > 7:
        _fail("REFERENCE", "Tham chiếu vượt giới hạn trang tính.")
    column = 0
    for letter in letters.upper():
        column = column * 26 + ord(letter) - ord("A") + 1
    row = int(row_text)
    if not 1 <= row <= MAX_ROW or not 1 <= column <= MAX_COLUMN:
        _fail("REFERENCE", "Tham chiếu vượt giới hạn trang tính.")
    return row, column, bool(absolute_row), bool(absolute_column)


def _column_letters(column: int) -> str:
    result = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _canonical(reference: str) -> str:
    row, column, _, _ = _coordinates(reference)
    return f"{_column_letters(column)}{row}"


def _decimal(text: str) -> Decimal:
    if len(text) > 128:
        _fail("PRECISION", "Số vượt giới hạn độ chính xác của bộ tính.")
    try:
        number = Decimal(text)
    except DecimalException:
        _fail("VALUE", "Giá trị số không hợp lệ.")
    return _checked(number)


def _checked(number: Decimal) -> Decimal:
    if not number.is_finite():
        _fail("VALUE", "Chỉ chấp nhận số thập phân hữu hạn.")
    if len(number.as_tuple().digits) > DECIMAL_PRECISION or abs(number.adjusted()) > 1000:
        _fail("PRECISION", "Số vượt giới hạn độ chính xác của bộ tính.")
    return number


def _tokens(formula: str, charge: Callable[[int], None]) -> list[_Token]:
    if not isinstance(formula, str) or not formula.startswith("="):
        _fail("SYNTAX", "Công thức phải bắt đầu bằng dấu =.")
    if len(formula) > MAX_FORMULA:
        _fail("LIMIT", "Công thức vượt giới hạn độ dài.")
    result: list[_Token] = []
    position = 1
    while position < len(formula):
        charge(1)
        character = formula[position]
        if character.isspace():
            position += 1
            continue
        start = position
        if character == '"':
            position += 1
            while position < len(formula):
                charge(1)
                if formula[position] == '"':
                    position += 1
                    if position < len(formula) and formula[position] == '"':
                        position += 1
                        continue
                    break
                position += 1
            else:
                _fail("SYNTAX", "Chuỗi trong công thức chưa đóng dấu nháy.")
            result.append(_Token("STRING", formula[start + 1:position - 1].replace('""', '"'), start, position))
            continue
        if character in "[]!|'":
            _fail("EXTERNAL_REFERENCE", "Không hỗ trợ tham chiếu sheet/tệp ngoài hoặc DDE.")
        match = _NUMBER.match(formula, position)
        if match:
            position = match.end()
            result.append(_Token("NUMBER", match.group(), start, position))
            continue
        match = _WORD.match(formula, position)
        if match:
            position = match.end()
            word = match.group()
            following = formula[position:].lstrip()
            kind = "REF" if _REF.fullmatch(word) and not following.startswith("(") else "NAME"
            result.append(_Token(kind, word.upper(), start, position))
            continue
        pair = formula[position:position + 2]
        if pair in ("<=", ">=", "<>"):
            position += 2
            result.append(_Token(pair, pair, start, position))
            continue
        if character in "+-*/^%&=<>():,;":
            position += 1
            result.append(_Token(character, character, start, position))
            continue
        _fail("UNSUPPORTED", "Ký hiệu hoặc tính năng công thức chưa được hỗ trợ.")
    result.append(_Token("EOF", "", position, position))
    return result


class _Parser:
    _binding = {"=": 10, "<>": 10, "<": 10, ">": 10, "<=": 10, ">=": 10,
                "&": 15, "+": 20, "-": 20, "*": 30, "/": 30, "^": 40}

    def __init__(self, tokens: list[_Token], max_depth: int) -> None:
        self.tokens = tokens
        self.position = 0
        self.max_depth = max_depth
        self.separator: str | None = None

    def _take(self, kind: str | None = None) -> _Token:
        token = self.tokens[self.position]
        if kind is not None and token.kind != kind:
            _fail("SYNTAX", "Cú pháp công thức không hợp lệ.")
        self.position += 1
        return token

    def parse(self) -> _Node:
        result = self._expression(0, 0)
        if self.tokens[self.position].kind != "EOF":
            _fail("SYNTAX", "Công thức có nội dung thừa hoặc cú pháp không hợp lệ.")
        return result

    def _expression(self, minimum: int, depth: int) -> _Node:
        if depth >= self.max_depth:
            _fail("DEPTH", "Công thức vượt giới hạn độ sâu.")
        token = self._take()
        if token.kind == "NUMBER":
            left = _Node("literal", _decimal(token.value))
        elif token.kind == "STRING":
            left = _Node("literal", token.value)
        elif token.kind == "REF":
            reference = _canonical(token.value)
            if self.tokens[self.position].kind == ":":
                self._take(":")
                end = _canonical(self._take("REF").value)
                left = _Node("range", (reference, end))
            else:
                left = _Node("reference", reference)
        elif token.kind == "NAME":
            if token.value in ("TRUE", "FALSE") and self.tokens[self.position].kind != "(":
                left = _Node("literal", token.value == "TRUE")
            else:
                if token.value not in FUNCTIONS:
                    _fail("UNSUPPORTED", "Tên hoặc hàm công thức chưa được hỗ trợ.")
                self._take("(")
                arguments = []
                if self.tokens[self.position].kind != ")":
                    while True:
                        arguments.append(self._expression(0, depth + 1))
                        separator = self.tokens[self.position].kind
                        if separator not in (",", ";"):
                            break
                        if self.separator is not None and self.separator != separator:
                            _fail("SYNTAX", "Không trộn dấu phẩy và chấm phẩy trong một công thức.")
                        self.separator = separator
                        self._take()
                self._take(")")
                left = _Node("call", token.value, tuple(arguments))
        elif token.kind in ("+", "-"):
            left = _Node("unary", token.kind, (self._expression(35, depth + 1),))
        elif token.kind == "(":
            left = self._expression(0, depth + 1)
            self._take(")")
        else:
            _fail("SYNTAX", "Thiếu giá trị hoặc biểu thức trong công thức.")
        while True:
            operator = self.tokens[self.position].kind
            if operator == "%" and 50 >= minimum:
                self._take()
                left = _Node("unary", "%", (left,))
                continue
            binding = self._binding.get(operator, -1)
            if binding < minimum:
                break
            self._take()
            right = self._expression(binding if operator == "^" else binding + 1, depth + 1)
            left = _Node("binary", operator, (left, right))
        return left


@dataclass(frozen=True)
class _Range:
    row: int
    column: int
    end_row: int
    end_column: int

    @property
    def shape(self) -> tuple[int, int]:
        return self.end_row - self.row + 1, self.end_column - self.column + 1

    def references(self) -> Iterator[str]:
        for row in range(self.row, self.end_row + 1):
            for column in range(self.column, self.end_column + 1):
                yield f"{_column_letters(column)}{row}"


class FormulaEngine:
    """One evaluation is a bounded snapshot; instances are not thread-safe.

    Dependencies and caches reset on evaluate(). Graph edges include only cells
    actually visited (IF is lazy). Reuse the engine only with a stable resolver.
    """

    def __init__(self, resolve: Callable[[str], object], *, max_range: int = 10_000,
                 max_cost: int = 100_000, max_depth: int = 64,
                 cancelled: Callable[[], bool] | None = None) -> None:
        if min(max_range, max_cost, max_depth) < 1 or max_depth > 128:
            raise ValueError("Formula limits must be positive; max_depth must be <= 128")
        self.resolve = resolve
        self.max_range = max_range
        self.max_cost = max_cost
        self.max_depth = max_depth
        self.cancelled = cancelled
        self.dependencies: set[str] = set()
        self.dependency_graph: dict[str, set[str]] = {}
        self.cost = 0
        self._active: list[str] = []
        self._memo: dict[str, Scalar] = {}

    def _charge(self, count: int = 1) -> None:
        self.cost += count
        if self.cancelled is not None and self.cancelled():
            _fail("CANCELLED", "Đã hủy tính công thức.")
        if self.cost > self.max_cost:
            _fail("COST", "Công thức vượt ngân sách tính toán.")

    def evaluate(self, formula: str) -> Scalar:
        self.cost = 0
        self.dependencies = set()
        self.dependency_graph = {"<formula>": set()}
        self._active = []
        self._memo = {}
        # Isolate from callers' precision, rounding and trap configuration.
        with localcontext() as context:
            context.prec = DECIMAL_PRECISION
            context.rounding = ROUND_HALF_UP
            context.Emax = 1000
            context.Emin = -1000
            for signal in context.traps:
                context.traps[signal] = False
            context.traps[InvalidOperation] = True
            context.traps[Overflow] = True
            try:
                result = self._formula(formula, 0)
                if isinstance(result, _Range):
                    _fail("VALUE", "Range chỉ được dùng làm đối số hàm hỗ trợ.")
                return result
            except FormulaError:
                raise
            except RecursionError:
                _fail("DEPTH", "Công thức vượt giới hạn độ sâu.")
            except DecimalException:
                _fail("PRECISION", "Phép tính vượt giới hạn độ chính xác.")

    def _formula(self, text: str, depth: int) -> Scalar | _Range:
        self._depth(depth)
        tree = _Parser(_tokens(text, self._charge), self.max_depth).parse()
        return self._eval(tree, depth)

    def _depth(self, depth: int) -> None:
        self._charge()
        if depth >= self.max_depth:
            _fail("DEPTH", "Công thức vượt giới hạn độ sâu.")

    def _cell(self, reference: str, depth: int) -> Scalar:
        self._depth(depth)
        self.dependencies.add(reference)
        owner = self._active[-1] if self._active else "<formula>"
        self.dependency_graph.setdefault(owner, set()).add(reference)
        if reference in self._active:
            _fail("CIRCULAR", "Công thức có tham chiếu vòng.")
        if reference in self._memo:
            return self._memo[reference]
        try:
            value = self.resolve(reference)
        except FormulaError:
            raise
        except (KeyError, IndexError):
            _fail("REFERENCE", "Ô tham chiếu không có trong snapshot đã xác nhận.")
        if isinstance(value, LiteralCell):
            literal = self._scalar(value.value)
            self._memo[reference] = literal
            return literal
        if isinstance(value, FormulaCell):
            if value.formula_text is not None:
                if not isinstance(value.formula_text, str) or not value.formula_text.startswith("="):
                    _fail("SYNTAX", "Ô công thức phải chứa raw formula bắt đầu bằng dấu =.")
                value = value.formula_text
            else:
                status_codes = {"unsupported": "UNSUPPORTED", "external_reference": "EXTERNAL_REFERENCE",
                                "circular": "CIRCULAR", "missing_cache": "MISSING_CACHE"}
                code = status_codes.get(value.calculation_status or "",
                                        "MISSING_CACHE" if value.cached_value is None else "CACHE_ONLY")
                _fail(code, "Ô công thức chưa có giá trị được bộ tính xác nhận.")
        if isinstance(value, str) and value.startswith("="):
            self._active.append(reference)
            self.dependency_graph.setdefault(reference, set())
            try:
                value = self._formula(value, depth + 1)
            finally:
                self._active.pop()
        value = self._scalar(value)
        self._memo[reference] = value
        return value

    @staticmethod
    def _scalar(value: object) -> Scalar:
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, Decimal):
            return _checked(value)
        if isinstance(value, int):
            return _checked(Decimal(value))
        if isinstance(value, str):
            if len(value) > MAX_TEXT:
                _fail("LIMIT", "Nội dung ô vượt giới hạn độ dài.")
            return value
        _fail("VALUE", "Ô phải là Decimal, số nguyên, text, boolean hoặc blank; không chấp nhận float.")

    @staticmethod
    def _numeric(value: object) -> Decimal:
        if value is None:
            return Decimal(0)
        if isinstance(value, bool):
            return Decimal(int(value))
        if isinstance(value, Decimal):
            return value
        _fail("VALUE", "Phép tính cần số; text không được tự đổi thành số.")

    @staticmethod
    def _truth(value: object) -> bool:
        if value is None:
            return False
        if isinstance(value, (Decimal, bool)):
            return bool(value)
        _fail("VALUE", "Điều kiện IF phải là số, boolean hoặc blank.")

    def _eval(self, node: _Node, depth: int) -> Scalar | _Range:
        self._depth(depth)
        if node.kind == "literal":
            return node.value
        if node.kind == "reference":
            return self._cell(node.value, depth + 1)
        if node.kind == "range":
            start, end = node.value
            row, column, _, _ = _coordinates(start)
            end_row, end_column, _, _ = _coordinates(end)
            region = _Range(min(row, end_row), min(column, end_column),
                            max(row, end_row), max(column, end_column))
            height, width = region.shape
            if height * width > self.max_range:
                _fail("RANGE_LIMIT", "Range vượt giới hạn số ô cho một phép tính.")
            return region
        if node.kind == "call":
            return self._call(node.value, node.children, depth + 1)
        if node.kind == "unary":
            value = self._numeric(self._eval(node.children[0], depth + 1))
            if node.value == "+":
                return value
            if node.value == "-":
                return value.copy_negate()
            return self._arithmetic("/", value, Decimal(100))
        left = self._eval(node.children[0], depth + 1)
        right = self._eval(node.children[1], depth + 1)
        if isinstance(left, _Range) or isinstance(right, _Range):
            _fail("VALUE", "Không hỗ trợ phép toán trực tiếp trên range.")
        if node.value in ("=", "<>", "<", ">", "<=", ">="):
            return self._compare(left, right, node.value)
        if node.value == "&":
            def text(value: Scalar) -> str:
                if value is None:
                    return ""
                if isinstance(value, bool):
                    return "TRUE" if value else "FALSE"
                return str(value)
            return self._scalar(text(left) + text(right))
        return self._arithmetic(node.value, self._numeric(left), self._numeric(right))

    def _arithmetic(self, operator: str, left: Decimal, right: Decimal) -> Decimal:
        self._charge()
        # Exact addition/multiplication must not silently discard small amounts.
        # Division (and negative powers) use the documented 50-digit context.
        with localcontext() as context:
            context.traps[Inexact] = operator not in ("/",) and not (operator == "^" and right < 0)
            if operator == "+":
                result = left + right
            elif operator == "-":
                result = left - right
            elif operator == "*":
                result = left * right
            elif operator == "/":
                if not right:
                    _fail("DIV_ZERO", "Không thể chia cho 0.")
                result = left / right
            else:
                if right != right.to_integral_value() or abs(right) > 1000:
                    _fail("UNSUPPORTED", "Số mũ phải là số nguyên trong khoảng -1000 đến 1000.")
                if not left and right < 0:
                    _fail("DIV_ZERO", "Không thể nâng 0 lên số mũ âm.")
                if not left and not right:
                    _fail("VALUE", "Không hỗ trợ 0 mũ 0.")
                self._charge(int(abs(right)))
                result = left ** int(right)
            return _checked(result)

    @staticmethod
    def _compare(left: Scalar, right: Scalar, operator: str) -> bool:
        if left is None:
            left = "" if isinstance(right, str) else (False if isinstance(right, bool) else Decimal(0))
        if right is None:
            right = "" if isinstance(left, str) else (False if isinstance(left, bool) else Decimal(0))
        if isinstance(left, str) and isinstance(right, str):
            left, right = left.casefold(), right.casefold()
        if type(left) is not type(right):
            if operator in ("=", "<>"):
                return operator == "<>"
            _fail("VALUE", "Không so sánh thứ tự giữa các kiểu dữ liệu khác nhau.")
        if operator == "=":
            return left == right
        if operator == "<>":
            return left != right
        if operator == "<":
            return left < right
        if operator == ">":
            return left > right
        if operator == "<=":
            return left <= right
        return left >= right

    def _values(self, value: Scalar | _Range, depth: int) -> Iterator[Scalar]:
        if isinstance(value, _Range):
            for reference in value.references():
                yield self._cell(reference, depth + 1)
        else:
            yield value

    def _range_argument(self, node: _Node, depth: int) -> _Range:
        if node.kind == "reference":
            self._depth(depth)
            row, column, _, _ = _coordinates(node.value)
            return _Range(row, column, row, column)
        region = self._eval(node, depth)
        if not isinstance(region, _Range):
            _fail("ARGUMENTS", "SUMIF/COUNTIF cần range điều kiện và range tổng.")
        return region

    def _call(self, name: str, arguments: tuple[_Node, ...], depth: int) -> Scalar:
        self._depth(depth)
        if name == "IF":
            if len(arguments) not in (2, 3):
                _fail("ARGUMENTS", "IF cần hai hoặc ba đối số.")
            condition = self._truth(self._eval(arguments[0], depth + 1))
            if condition:
                result = self._eval(arguments[1], depth + 1)
            else:
                result = self._eval(arguments[2], depth + 1) if len(arguments) == 3 else False
            if isinstance(result, _Range):
                _fail("VALUE", "Nhánh IF phải trả về một giá trị.")
            return result
        if name == "ROUND":
            if len(arguments) != 2:
                _fail("ARGUMENTS", "ROUND cần hai đối số.")
            value = self._numeric(self._eval(arguments[0], depth + 1))
            places = self._numeric(self._eval(arguments[1], depth + 1))
            if places != places.to_integral_value() or abs(places) > DECIMAL_PRECISION:
                _fail("ARGUMENTS", "Số chữ số ROUND phải là số nguyên từ -50 đến 50.")
            return _checked(value.quantize(Decimal(1).scaleb(-int(places)), rounding=ROUND_HALF_UP))
        if name in ("SUMIF", "COUNTIF"):
            if len(arguments) not in ((2, 3) if name == "SUMIF" else (2,)):
                _fail("ARGUMENTS", "Số đối số của SUMIF/COUNTIF không hợp lệ.")
            region = self._range_argument(arguments[0], depth + 1)
            criterion = self._eval(arguments[1], depth + 1)
            summed = self._range_argument(arguments[2], depth + 1) if len(arguments) == 3 else region
            if isinstance(criterion, _Range):
                _fail("ARGUMENTS", "SUMIF/COUNTIF cần range và điều kiện đơn.")
            if region.shape != summed.shape:
                _fail("RANGE_SHAPE", "Range điều kiện và range tổng phải cùng kích thước.")
            matches = self._criterion(criterion)
            total = Decimal(0)
            for reference, sum_reference in zip(region.references(), summed.references(), strict=True):
                if matches(self._cell(reference, depth + 1)):
                    if name == "COUNTIF":
                        total = self._arithmetic("+", total, Decimal(1))
                    else:
                        value = self._cell(sum_reference, depth + 1)
                        if isinstance(value, Decimal):
                            total = self._arithmetic("+", total, value)
            return total
        if not arguments and name not in ("SUM", "COUNT"):
            _fail("ARGUMENTS", "Hàm cần ít nhất một đối số.")
        total = Decimal(0)
        count = 0
        extreme: Decimal | None = None
        for argument in arguments:
            for value in self._values(self._eval(argument, depth + 1), depth + 1):
                self._charge()
                if not isinstance(value, Decimal):
                    continue
                count += 1
                if name in ("SUM", "AVERAGE"):
                    total = self._arithmetic("+", total, value)
                elif name == "MIN":
                    extreme = value if extreme is None else min(extreme, value)
                elif name == "MAX":
                    extreme = value if extreme is None else max(extreme, value)
        if name == "COUNT":
            return Decimal(count)
        if name == "AVERAGE":
            if not count:
                _fail("DIV_ZERO", "AVERAGE không có ô số để tính.")
            return self._arithmetic("/", total, Decimal(count))
        if name in ("MIN", "MAX"):
            return extreme if extreme is not None else Decimal(0)
        return total

    def _criterion(self, criterion: Scalar) -> Callable[[Scalar], bool]:
        operator = "="
        target = criterion
        if isinstance(criterion, str):
            if len(criterion) > 1024:
                _fail("LIMIT", "Điều kiện vượt giới hạn độ dài.")
            match = re.match(r"^(<=|>=|<>|=|<|>)", criterion)
            if match:
                operator = match.group()
                target = criterion[len(operator):]
            if _NUMERIC_CRITERION.fullmatch(target):
                target = _decimal(target)
        if isinstance(target, str) and operator in ("=", "<>"):
            pattern: list[tuple[str, str]] = []
            index = 0
            folded = target.casefold()
            while index < len(folded):
                self._charge()
                character = folded[index]
                if character == "~" and index + 1 < len(folded) and folded[index + 1] in "*?~":
                    index += 1
                    pattern.append(("literal", folded[index]))
                elif character == "*":
                    if not pattern or pattern[-1][0] != "star":
                        pattern.append(("star", ""))
                elif character == "?":
                    pattern.append(("any", ""))
                else:
                    pattern.append(("literal", character))
                index += 1

            def match_text(value: Scalar) -> bool:
                self._charge()
                if target == "" and value is None:
                    matched = True
                else:
                    matched = isinstance(value, str) and self._wildcard(pattern, value.casefold())
                return matched if operator == "=" else not matched
            return match_text

        def compare(value: Scalar) -> bool:
            self._charge()
            # Numeric criteria never coerce numeric text or blank into numbers.
            if type(value) is not type(target):
                return operator == "<>"
            return self._compare(value, target, operator)
        return compare

    def _wildcard(self, pattern: list[tuple[str, str]], text: str) -> bool:
        # Iterative glob matcher; every backtracking step consumes bounded cost.
        position = token = 0
        star = -1
        retry = 0
        while position < len(text):
            self._charge()
            if token < len(pattern) and (pattern[token][0] == "any" or
                                        pattern[token] == ("literal", text[position])):
                token += 1
                position += 1
            elif token < len(pattern) and pattern[token][0] == "star":
                star = token
                token += 1
                retry = position
            elif star >= 0:
                token = star + 1
                retry += 1
                position = retry
            else:
                return False
        while token < len(pattern) and pattern[token][0] == "star":
            self._charge()
            token += 1
        return token == len(pattern)


def translate_formula(formula: str, row_delta: int, col_delta: int) -> str:
    """Translate copy/fill A1 references, respecting each $ anchor.

    This is deliberately not an insert/delete rewrite. Structural edits require
    a separate identity-aware operation and must be refused by the caller.
    """
    if type(row_delta) is not int or type(col_delta) is not int:
        raise TypeError("row_delta and col_delta must be integers")
    cost = 0

    def charge(count: int) -> None:
        nonlocal cost
        cost += count
        if cost > 100_000:
            _fail("COST", "Công thức vượt ngân sách dịch tham chiếu.")

    tokens = _tokens(formula, charge)
    _Parser(tokens, 64).parse()
    fragments = []
    position = 0
    for token in tokens:
        if token.kind != "REF":
            continue
        row, column, absolute_row, absolute_column = _coordinates(token.value)
        row += 0 if absolute_row else row_delta
        column += 0 if absolute_column else col_delta
        if not 1 <= row <= MAX_ROW or not 1 <= column <= MAX_COLUMN:
            _fail("REFERENCE", "Sao chép công thức làm tham chiếu vượt trang tính.")
        reference = ("$" if absolute_column else "") + _column_letters(column)
        reference += ("$" if absolute_row else "") + str(row)
        fragments.extend((formula[position:token.start], reference))
        position = token.end
    fragments.append(formula[position:])
    return "".join(fragments)
