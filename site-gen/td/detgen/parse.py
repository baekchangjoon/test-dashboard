"""bbtg 조건식 파서(설계 §5.2 "피연산자 분류", "연산자 정규화와 경계").

조건식은 위반 조건을 Java 식으로 적은 문자열이다. 이 모듈은 Java 문법만 안다(SUT 필드·클래스·상수 이름을 모른다).
결과는 논리합(OR) 안의 논리곱(AND) 목록, 곧 DNF다. 해석할 수 없으면 예외를 내지 않고 `Parsed(None, "unparsed")`를 돌려준다.

정규화 규칙:
- 피연산자 순서: 값 쪽(literal/constant/enum/clock)이 왼쪽이고 대상 쪽이 오른쪽이면 뒤집는다(`30 < f` → `f > 30`).
- 날짜: `now.isBefore(x)` → `x.isAfter(now)`, `now.isAfter(x)` → `x.isBefore(now)`.
- `!`는 원자식까지 밀어 넣는다(De Morgan). 모델에 없는 극성(`x.isAfter(now)`, `P.matcher(f).matches()` 긍정형 등)은 unparsed.
- 산술(`a * k < b`)은 피연산자 전체를 unresolved로 둔 관계식 하나로 남긴다(파생기가 미해결 관계로 기록하도록).
- 문법이 아는 메서드(isAfter/isBefore/matcher().matches()/equals/length/count*) 밖의 불리언 호출·변수는
  `Atom("==", unresolved, literal true|false)`로 둔다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal

OperandKind = Literal["request", "stored", "clock", "constant", "literal", "enum", "unresolved"]
AtomOp = Literal["<", "<=", ">", ">=", "==null", "!=null", "==", "!=", "isAfterNot", "isBefore",
                 "matchesNot", "equalsLit", "countGe"]


@dataclass(frozen=True)
class Operand:
    kind: OperandKind
    name: str
    detail: str = ""


@dataclass(frozen=True)
class Atom:
    op: AtomOp
    left: Operand
    right: Operand | None
    length: bool = False  # True면 left의 길이(`.length()`)를 비교한다


@dataclass(frozen=True)
class Parsed:
    disjuncts: tuple[tuple[Atom, ...], ...] | None  # OR of ANDs. 실패 시 None
    reason: str | None


UNPARSED = Parsed(None, "unparsed")
# bbtg 조건식에서 저장 상태(갱신 대상 엔티티)를 가리키는 수신자 이름(설계 §5.2 규약)
STORED_RECEIVER = "existing"
# 시계 표현식의 수신 타입(java.time API)
CLOCK_TYPES = frozenset({"LocalDate", "LocalDateTime"})
# DNF 전개 상한. 넘으면 해석을 포기한다
MAX_DISJUNCTS = 64

_TOKEN_PATTERN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<string>"(?:[^"\\\n]|\\.)*")
  | (?P<number>\d+(?:\.\d+)?[lLdDfF]?)
  | (?P<ident>[A-Za-z_$][A-Za-z0-9_$]*)
  | (?P<op>\|\||&&|==|!=|<=|>=|<|>|!|\(|\)|\.|,|\+|-|\*|/|%)
""", re.VERBOSE)
_UPPER_CONSTANT = re.compile(r"[A-Z][A-Z0-9_]*")
_UPPER_CAMEL = re.compile(r"[A-Z][A-Za-z0-9_$]*")
_COMPARE_OPS = ("<", "<=", ">", ">=", "==", "!=")
_FLIP = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "==": "==", "!=": "!="}
_NEGATE = {"<": ">=", "<=": ">", ">": "<=", ">=": "<", "==": "!=", "!=": "=="}
# 시계 값을 시계로 유지하는 java.time 이동 메서드. 그 밖의 이어진 호출(getYear 등)은 미해결
_CLOCK_SHIFT = re.compile(r"(?:plus|minus)[A-Za-z]*|atStartOfDay")
_VALUE_KINDS = frozenset({"literal", "constant", "enum", "clock"})


class _ParseError(Exception):
    """내부 실패 신호. `parse` 밖으로는 나가지 않는다."""


# --- 토큰 ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class _Token:
    kind: str  # string | number | ident | op | end
    text: str
    start: int
    end: int


def _tokenize(source: str) -> list[_Token]:
    tokens: list[_Token] = []
    position = 0
    while position < len(source):
        match = _TOKEN_PATTERN.match(source, position)
        if match is None:
            raise _ParseError(f"알 수 없는 문자: {source[position]!r}")
        kind = match.lastgroup
        if kind != "ws":
            tokens.append(_Token(kind, match.group(), match.start(), match.end()))
        position = match.end()
    tokens.append(_Token("end", "", len(source), len(source)))
    return tokens


# --- 식 AST(값 수준) -------------------------------------------------------------------------------

@dataclass(frozen=True)
class _Expr:
    start: int
    end: int


@dataclass(frozen=True)
class _Name(_Expr):
    ident: str


@dataclass(frozen=True)
class _Lit(_Expr):
    value: str
    kind: str  # number | string | boolean | null


@dataclass(frozen=True)
class _Field(_Expr):
    target: _Expr
    ident: str


@dataclass(frozen=True)
class _Call(_Expr):
    target: _Expr | None  # None이면 수신자 없는 호출
    method: str
    args: tuple[_Expr, ...]


@dataclass(frozen=True)
class _Arith(_Expr):
    pass  # 산술식: 구조는 쓰지 않고 원문 범위만 쓴다


# --- 조건 트리(논리 수준) ----------------------------------------------------------------------------

@dataclass(frozen=True)
class _Pred:
    """원자 술어. negated는 `!`가 몇 번 걸렸는지의 홀짝이다."""
    shape: str  # compare | date | matches | equals | boolean
    operator: str
    left: _Expr
    right: _Expr | None
    negated: bool = False


@dataclass(frozen=True)
class _Or:
    items: tuple


@dataclass(frozen=True)
class _And:
    items: tuple


@dataclass(frozen=True)
class _Not:
    item: object


class _Parser:
    """재귀 하강: `||` < `&&` < `!` < 비교 < 산술 < 후위(`.`·호출)."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.tokens = _tokenize(source)
        self.position = 0

    # 토큰 도우미
    def _peek(self, offset: int = 0) -> _Token:
        return self.tokens[min(self.position + offset, len(self.tokens) - 1)]

    def _take(self) -> _Token:
        token = self._peek()
        self.position += 1
        return token

    def _at(self, text: str) -> bool:
        token = self._peek()
        return token.kind == "op" and token.text == text

    def _expect(self, text: str) -> _Token:
        if not self._at(text):
            raise _ParseError(f"{text!r} 필요, {self._peek().text!r} 발견")
        return self._take()

    def parse_condition(self):
        tree = self._or()
        if self._peek().kind != "end":
            raise _ParseError(f"남은 토큰: {self._peek().text!r}")
        return tree

    # 논리 수준
    def _or(self):
        items = [self._and()]
        while self._at("||"):
            self._take()
            items.append(self._and())
        return items[0] if len(items) == 1 else _Or(tuple(items))

    def _and(self):
        items = [self._unary()]
        while self._at("&&"):
            self._take()
            items.append(self._unary())
        return items[0] if len(items) == 1 else _And(tuple(items))

    def _unary(self):
        if self._at("!"):
            self._take()
            return _Not(self._unary())
        if self._at("("):
            # 괄호가 논리 묶음인지 산술 묶음인지 먼저 논리로 시도하고, 뒤에 비교·산술 연산자가 오면 되돌린다
            saved = self.position
            try:
                self._take()
                group = self._or()
                self._expect(")")
                follower = self._peek()
                if not (follower.kind == "op" and follower.text in _COMPARE_OPS + ("+", "-", "*", "/", "%", ".")):
                    return group
            except _ParseError:
                pass
            self.position = saved
        return self._comparison()

    def _comparison(self):
        left = self._arith()
        token = self._peek()
        if token.kind == "op" and token.text in _COMPARE_OPS:
            self._take()
            right = self._arith()
            follower = self._peek()
            if follower.kind == "op" and follower.text in _COMPARE_OPS:
                raise _ParseError("연쇄 비교")
            return _Pred("compare", token.text, left, right)
        return _boolean_pred(left)

    # 값 수준
    def _arith(self) -> _Expr:
        start_token = self._peek()
        left = self._term()
        is_arith = False
        while self._peek().kind == "op" and self._peek().text in ("+", "-"):
            self._take()
            self._term()
            is_arith = True
        if is_arith:
            return _Arith(start_token.start, self.tokens[self.position - 1].end)
        return left

    def _term(self) -> _Expr:
        start_token = self._peek()
        left = self._signed()
        is_arith = False
        while self._peek().kind == "op" and self._peek().text in ("*", "/", "%"):
            self._take()
            self._signed()
            is_arith = True
        if is_arith:
            return _Arith(start_token.start, self.tokens[self.position - 1].end)
        return left

    def _signed(self) -> _Expr:
        if self._at("-"):
            minus = self._take()
            operand = self._signed()
            if isinstance(operand, _Lit) and operand.kind == "number" and operand.start == minus.end:
                return _Lit(minus.start, operand.end, "-" + operand.value, "number")
            return _Arith(minus.start, operand.end)
        return self._postfix()

    def _postfix(self) -> _Expr:
        expr = self._primary()
        while self._at("."):
            self._take()
            name = self._take()
            if name.kind != "ident":
                raise _ParseError("'.' 뒤 식별자 필요")
            if self._at("("):
                args, end = self._arguments()
                expr = _Call(expr.start, end, expr, name.text, args)
            else:
                expr = _Field(expr.start, name.end, expr, name.text)
        return expr

    def _arguments(self) -> tuple[tuple[_Expr, ...], int]:
        self._expect("(")
        args: list[_Expr] = []
        if not self._at(")"):
            args.append(self._arith())
            while self._at(","):
                self._take()
                args.append(self._arith())
        close = self._expect(")")
        return tuple(args), close.end

    def _primary(self) -> _Expr:
        token = self._peek()
        if token.kind == "number":
            self._take()
            return _Lit(token.start, token.end, token.text, "number")
        if token.kind == "string":
            self._take()
            return _Lit(token.start, token.end, _unquote(token.text), "string")
        if token.kind == "ident":
            self._take()
            if token.text in ("true", "false"):
                return _Lit(token.start, token.end, token.text, "boolean")
            if token.text == "null":
                return _Lit(token.start, token.end, "null", "null")
            if self._at("("):
                args, end = self._arguments()
                return _Call(token.start, end, None, token.text, args)
            return _Name(token.start, token.end, token.text)
        if self._at("("):
            open_token = self._take()
            inner = self._arith()
            close = self._expect(")")
            if isinstance(inner, _Arith):
                return _Arith(open_token.start, close.end)
            return inner
        raise _ParseError(f"피연산자 필요, {token.text!r} 발견")


def _unquote(text: str) -> str:
    body = text[1:-1]
    return re.sub(r"\\(.)", r"\1", body)


def _boolean_pred(expr: _Expr) -> _Pred:
    """비교 연산자 없이 쓰인 불리언 식을 술어로 바꾼다."""
    if isinstance(expr, _Call) and expr.target is not None:
        if expr.method in ("isAfter", "isBefore") and len(expr.args) == 1:
            return _Pred("date", expr.method, expr.target, expr.args[0])
        if (expr.method == "matches" and not expr.args and isinstance(expr.target, _Call)
                and expr.target.method == "matcher" and len(expr.target.args) == 1 and expr.target.target is not None):
            return _Pred("matches", "matches", expr.target.args[0], expr.target.target)
        if expr.method == "equals" and len(expr.args) == 1:
            return _Pred("equals", "equals", expr.target, expr.args[0])
    if isinstance(expr, (_Call, _Name, _Field)):
        return _Pred("boolean", "boolean", expr, None)
    raise _ParseError("불리언 식이 아님")


# --- DNF 전개 -----------------------------------------------------------------------------------

def _to_dnf(node, negated: bool = False) -> list[list[_Pred]]:
    if isinstance(node, _Not):
        return _to_dnf(node.item, not negated)
    if isinstance(node, _Pred):
        return [[replace(node, negated=node.negated != negated)]]
    is_or = isinstance(node, _Or)
    if negated:
        is_or = not is_or  # De Morgan
    parts = [_to_dnf(item, negated) for item in node.items]
    if is_or:
        result = [conjunct for part in parts for conjunct in part]
    else:
        result = [[]]
        for part in parts:
            result = [left + right for left in result for right in part]
            if len(result) > MAX_DISJUNCTS:
                raise _ParseError("DNF 상한 초과")
    if len(result) > MAX_DISJUNCTS:
        raise _ParseError("DNF 상한 초과")
    return result


# --- 피연산자 분류와 원자식 변환 ------------------------------------------------------------------

class _Classifier:
    def __init__(self, source: str, request_var: str | None) -> None:
        self.source = source
        self.request_var = request_var or None

    def text(self, expr: _Expr) -> str:
        """원문 범위를 공백 하나로 접어 돌려준다(줄바꿈·탭 제거)."""
        return re.sub(r"\s+", " ", self.source[expr.start:expr.end]).strip()

    def operand(self, expr: _Expr) -> Operand:
        if isinstance(expr, _Lit):
            return Operand("literal", expr.value, expr.kind)
        if isinstance(expr, _Name):
            if expr.ident == self.request_var:
                return Operand("request", expr.ident)
            if _UPPER_CONSTANT.fullmatch(expr.ident):
                return Operand("constant", expr.ident)
            return Operand("unresolved", expr.ident)
        if isinstance(expr, _Field):
            if (isinstance(expr.target, _Name) and _UPPER_CAMEL.fullmatch(expr.target.ident)
                    and not _UPPER_CONSTANT.fullmatch(expr.target.ident) and _UPPER_CONSTANT.fullmatch(expr.ident)):
                return Operand("enum", expr.ident, expr.target.ident)
            return Operand("unresolved", self.text(expr))
        if isinstance(expr, _Call):
            return self._call_operand(expr)
        return Operand("unresolved", self.text(expr))

    def _call_operand(self, expr: _Call) -> Operand:
        target = expr.target
        if isinstance(target, _Name) and not expr.args:
            if self.request_var is not None and target.ident == self.request_var:
                return Operand("request", expr.method)
            if target.ident == STORED_RECEIVER and expr.method.startswith("get") and len(expr.method) > 3:
                return Operand("stored", _decapitalize(expr.method[3:]))
            if target.ident in CLOCK_TYPES and expr.method == "now":
                return Operand("clock", self.text(expr))
        # 시계에 이어진 이동 메서드(plus*/minus*/atStartOfDay)만 시계로 두고 이어진 부분을 detail에 남긴다
        if target is not None:
            base = self._call_operand(target) if isinstance(target, _Call) else None
            if base is not None and base.kind == "clock" and _CLOCK_SHIFT.fullmatch(expr.method):
                suffix = self.source[target.end:expr.end]
                return Operand("clock", base.name, base.detail + re.sub(r"\s+", "", suffix))
        return Operand("unresolved", self.text(expr))

    def is_value(self, operand: Operand) -> bool:
        return operand.kind in _VALUE_KINDS

    def atom(self, pred: _Pred) -> Atom:
        if pred.shape == "compare":
            return self._compare_atom(pred)
        if pred.shape == "date":
            return self._date_atom(pred)
        if pred.shape == "matches":
            if not pred.negated:
                raise _ParseError("matches 긍정형은 모델에 없음")
            return Atom("matchesNot", self.operand(pred.left), self.operand(pred.right))
        if pred.shape == "equals":
            return self._equals_atom(pred)
        return Atom("==", self.operand(pred.left), Operand("literal", "false" if pred.negated else "true", "boolean"))

    def _compare_atom(self, pred: _Pred) -> Atom:
        operator = _NEGATE[pred.operator] if pred.negated else pred.operator
        left_expr, right_expr = pred.left, pred.right
        if isinstance(left_expr, _Lit) and left_expr.kind == "null":
            left_expr, right_expr = right_expr, left_expr
            operator = _FLIP[operator]
        if isinstance(right_expr, _Lit) and right_expr.kind == "null":
            if operator not in ("==", "!="):
                raise _ParseError("null과 대소 비교")
            if isinstance(left_expr, _Lit) and left_expr.kind == "null":
                raise _ParseError("null == null")
            return Atom("==null" if operator == "==" else "!=null", self.operand(left_expr), None)
        left_length = _length_target(left_expr)
        right_length = _length_target(right_expr)
        left = self.operand(left_length or left_expr)
        right = self.operand(right_length or right_expr)
        flipped = self.is_value(left) and not self.is_value(right)
        if flipped:
            left, right = right, left
            left_expr, right_expr = right_expr, left_expr
            left_length, right_length = right_length, left_length
            operator = _FLIP[operator]
        if right_length is not None:
            # 길이는 왼쪽 피연산자에만 붙는다. 양쪽 길이 비교 등은 원문 그대로 미해결로 둔다
            right = Operand("unresolved", self.text(right_expr))
        if left_length is None and self._is_count_query(left_expr):
            if operator == ">=":
                return Atom("countGe", self._count_operand(left_expr), right)
            left = Operand("unresolved", self.text(left_expr))
        return Atom(operator, left, right, length=left_length is not None)

    def _is_count_query(self, expr: _Expr) -> bool:
        """`count*` 이름의 호출이면서 수신자가 요청·저장 상태가 아닐 때만 count 질의로 본다(`req.countryCode()`는 요청 필드)."""
        if not (isinstance(expr, _Call) and expr.method.startswith("count")):
            return False
        if expr.target is None:
            return True
        return self.operand(expr.target).kind not in ("request", "stored")

    def _count_operand(self, call: _Call) -> Operand:
        """count 질의의 인자 중 요청 필드가 정확히 하나면 그 요청 피연산자, 아니면 호출 전체를 미해결로 둔다."""
        operands = [self.operand(argument) for argument in call.args]
        enum_detail = ",".join(f"{item.detail}.{item.name}" for item in operands if item.kind == "enum")
        requests = [item for item in operands if item.kind == "request"]
        if len(requests) == 1:
            return Operand("request", requests[0].name, enum_detail)
        return Operand("unresolved", self.text(call), enum_detail)

    def _date_atom(self, pred: _Pred) -> Atom:
        method = pred.operator
        left = self.operand(pred.left)
        right = self.operand(pred.right)
        if self.is_value(left) and not self.is_value(right):
            # now.isBefore(x) == x.isAfter(now)
            left, right = right, left
            method = "isAfter" if method == "isBefore" else "isBefore"
        if method == "isAfter" and pred.negated:
            return Atom("isAfterNot", left, right)
        if method == "isBefore" and not pred.negated:
            return Atom("isBefore", left, right)
        raise _ParseError("모델에 없는 날짜 비교 극성")

    def _equals_atom(self, pred: _Pred) -> Atom:
        receiver, argument = pred.left, pred.right
        if isinstance(argument, _Lit) and argument.kind == "string" and not (
                isinstance(receiver, _Lit) and receiver.kind == "string"):
            receiver, argument = argument, receiver
        if isinstance(receiver, _Lit) and receiver.kind == "string":
            subject = self.operand(argument)
            literal = self.operand(receiver)
            return Atom("!=" if pred.negated else "equalsLit", subject, literal)
        left, right = self.operand(receiver), self.operand(argument)
        if self.is_value(left) and not self.is_value(right):
            left, right = right, left
        return Atom("!=" if pred.negated else "==", left, right)


def _length_target(expr: _Expr) -> _Expr | None:
    if isinstance(expr, _Call) and expr.method == "length" and not expr.args and expr.target is not None:
        return expr.target
    return None


def _decapitalize(name: str) -> str:
    """java.beans.Introspector.decapitalize 규칙: 앞 두 글자가 모두 대문자면 그대로 둔다."""
    if len(name) > 1 and name[0].isupper() and name[1].isupper():
        return name
    return name[:1].lower() + name[1:]


def parse(condition: str, request_var: str | None) -> Parsed:
    """조건식을 DNF 원자식으로 바꾼다. 어떤 입력에도 예외를 내지 않는다."""
    if not isinstance(condition, str) or not condition.strip():
        return UNPARSED
    try:
        tree = _Parser(condition).parse_condition()
        classifier = _Classifier(condition, request_var)
        disjuncts = tuple(tuple(classifier.atom(pred) for pred in conjunct) for conjunct in _to_dnf(tree))
    except Exception:  # 어떤 내부 실패도 밖으로 내지 않는다(never-raise 계약)
        return UNPARSED
    return Parsed(disjuncts, None)
