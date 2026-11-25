"""Row-level security predicate engine: the only implementation module.

The module implements SQL-style three-valued logic (``true`` / ``false`` /
``unknown``).  ``unknown`` is a first-class result: it is never silently
coerced to either boolean, and an ``unknown`` predicate does not admit a row.
"""

# Three-valued result tokens.
TRUE = "true"
FALSE = "false"
UNKNOWN = "unknown"


def tri_and(a: str, b: str) -> str:
    """Return three-valued conjunction of a and b.

    Inputs and outputs are exactly true, false, or unknown. False dominates;
    otherwise unknown dominates; true is the identity.
    """
    # Defect 01 fix: unknown is *not* false.  False wins over everything,
    # unknown wins over true, and true is the identity.
    if a == FALSE or b == FALSE:
        return FALSE
    if a == UNKNOWN or b == UNKNOWN:
        return UNKNOWN
    return TRUE


def tri_or(a: str, b: str) -> str:
    """Return three-valued disjunction of a and b.

    Inputs and outputs are exactly true, false, or unknown. True dominates;
    otherwise unknown dominates; false is the identity.
    """
    # Defect 02 fix: unknown is *not* true.  True wins over everything,
    # unknown wins over false, and false is the identity.
    if a == TRUE or b == TRUE:
        return TRUE
    if a == UNKNOWN or b == UNKNOWN:
        return UNKNOWN
    return FALSE


def _row_field(row, field):
    """Return the row's field value; a missing field is SQL NULL (None)."""
    if isinstance(row, dict):
        return row.get(field, None)
    try:
        return row[field]
    except (KeyError, IndexError, TypeError):
        return None


def _compare_values(op: str, actual, expected) -> str:
    """Compare two non-NULL Python values and return a truth token."""
    if op == "eq":
        matched = actual == expected
    elif op == "ne":
        matched = actual != expected
    elif op == "lt":
        matched = actual < expected
    elif op == "le":
        matched = actual <= expected
    elif op == "gt":
        matched = actual > expected
    elif op == "ge":
        matched = actual >= expected
    else:
        raise ValueError(f"unsupported comparison operator: {op!r}")
    return TRUE if matched else FALSE


def evaluate(predicate: dict, row: dict) -> str:
    """Evaluate a predicate against one row and return true, false, or unknown.

    A missing field and a field whose value is None both count as SQL NULL.
    Any comparison involving NULL is unknown. is_null is true exactly for
    SQL NULL, and is_not_null is its complement. and and or must combine
    child results with tri_and and tri_or rather than coercing them to bool.
    """
    op = predicate["op"]

    if op == "and":
        # Defect 06 fix: fold *every* child with the commutative, associative
        # tri_and instead of Python short-circuit truthiness.  Each child is
        # always evaluated so a leading unknown cannot hide a later false;
        # the result is independent of operand order.
        result = TRUE  # conjunction identity
        for child in predicate.get("args", ()):  # evaluate all operands
            result = tri_and(result, evaluate(child, row))
        return result

    if op == "or":
        # Same full fold for disjunction (true dominates, so a later true is
        # never hidden by an earlier unknown).
        result = FALSE  # disjunction identity
        for child in predicate.get("args", ()):
            result = tri_or(result, evaluate(child, row))
        return result

    field = predicate["field"]
    actual = _row_field(row, field)

    if op == "is_null":
        return TRUE if actual is None else FALSE

    if op == "is_not_null":
        return FALSE if actual is None else TRUE

    expected = predicate["value"]

    # Defect 03/05 fix: any scalar comparison touching SQL NULL is unknown.
    # This covers a missing/None row field *and* a NULL literal on the
    # predicate side (so NULL = NULL is unknown, never a match).
    if actual is None or expected is None:
        return UNKNOWN

    try:
        return _compare_values(op, actual, expected)
    except TypeError:
        # Ordering between incomparable types is undefined; treat it as
        # unknown (which admits() still rejects, so the failure is closed).
        return UNKNOWN


def admits(predicate: dict, row: dict) -> bool:
    """Return True only when evaluate returns true.

    Both false and unknown must be rejected. The return value is a bool.
    """
    # Defect 04 fix: identity comparison against the exact "true" token.
    # ``evaluate(...) == "true"`` yields a real bool and never treats
    # unknown as truthy.
    return evaluate(predicate, row) == TRUE


def _structural_key(node):
    """Build a hashable structural fingerprint.

    Dict keys are sorted so the fingerprint is independent of dict insertion
    order, and type tags keep Python's ``1`` and ``True`` (which compare
    equal) as distinct AST values.
    """
    if isinstance(node, dict):
        return (
            "dict",
            tuple(sorted((str(k), _structural_key(v)) for k, v in node.items())),
        )
    if isinstance(node, (list, tuple)):
        return ("seq", tuple(_structural_key(v) for v in node))
    return (type(node).__name__, repr(node))


def combine(predicates) -> dict:
    """Return one conjunction of all predicates.

    The result must be independent of input order and must remove operands
    that are structurally identical. A single distinct operand may be
    returned directly or wrapped in an and node.
    """
    # Defect 07 fix: de-duplicate structurally identical operands.  Order is
    # preserved after de-duplication; order independence of the *result* is
    # guaranteed by tri_and's commutativity in evaluate().
    distinct = []
    seen = set()
    for predicate in predicates:
        key = _structural_key(predicate)
        if key in seen:
            continue
        seen.add(key)
        distinct.append(predicate)

    if len(distinct) == 1:
        return distinct[0]
    if not distinct:
        # Identity of conjunction is TRUE; represent as an empty and-node,
        # which evaluate() folds to "true".
        return {"op": "and", "args": []}
    return {"op": "and", "args": distinct}


def expand_view(view: dict, predicates) -> dict:
    """Expand a view to its effective predicate AST.

    view is a mapping with a predicate entry describing the view filter.
    predicates are predicates bound to the view's base table. The result is
    the conjunction of the view predicate and every base predicate; base
    predicates must never be dropped.
    """
    # Defect 08 fix: always conjoin the view predicate with *all* base-table
    # predicates instead of returning (or expanding to) only the view filter.
    base_predicates = list(predicates) if predicates is not None else []
    return combine([view["predicate"], *base_predicates])


def predicate_batch(rows, policy) -> dict:
    """Evaluate policy for every row and return {row_index: bool}.

    Each row is evaluated in isolation. No NULL set, result, or other row
    context may leak from one row or one batch call to the next.
    """
    # Defect 10 fix: a fresh, side-effect-free admits() call per row.  There
    # is deliberately no shared mutable "current row"/NULL-set state, so the
    # second row can never inherit the first row's NULL fields.
    return {
        index: admits(policy, row)
        for index, row in enumerate(rows)
    }


# ---------------------------------------------------------------------------
# Parser (defect 09)
# ---------------------------------------------------------------------------
#
# Hand-written tokenizer + recursive-descent parser.  String literals are
# scanned whole and their contents always stay *data*: keywords, operators,
# quotes and semicolons inside them can never become tokens.  Any construct
# outside the documented grammar -- concatenation (``||``), comments,
# semicolons, illegal characters and trailing tokens -- raises ValueError.


_TWO_CHAR_OPS = {">=", "<=", "!=", "<>", "=="}
_ONE_CHAR_OPS = {"=", "<", ">"}
_OP_MAP = {
    "=": "eq",
    "==": "eq",
    "!=": "ne",
    "<>": "ne",
    "<": "lt",
    "<=": "le",
    ">": "gt",
    ">=": "ge",
}


def _scan_quoted(text: str, start: int, quote: str):
    """Scan a quoted literal starting at ``start`` (the opening quote).

    Returns ``(value, next_index)``.  Supports SQL-style doubled quotes
    (``'it''s'``) plus backslash escapes for quote/backslash and the common
    ``\\n \\t \\r`` escapes.  Raises ValueError on an unterminated literal.
    """
    i = start + 1
    n = len(text)
    chars = []
    simple_escapes = {"n": "\n", "t": "\t", "r": "\r", "0": "\0"}

    while i < n:
        ch = text[i]

        if ch == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt in (quote, "\\"):
                chars.append(nxt)
            elif nxt in simple_escapes:
                chars.append(simple_escapes[nxt])
            else:
                # Unknown escape: preserve the backslash literally (SQL
                # convention) and keep the following character as data.
                chars.append("\\")
                chars.append(nxt)
            i += 2
            continue

        if ch == quote:
            # SQL doubled quote -> one literal quote.
            if i + 1 < n and text[i + 1] == quote:
                chars.append(quote)
                i += 2
                continue
            return "".join(chars), i + 1

        chars.append(ch)
        i += 1

    raise ValueError("unterminated string literal")


def _tokenize(text: str):
    tokens = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if ch.isspace():
            i += 1
            continue

        # Explicitly reject comments rather than stripping them (stripping
        # would let payloads hidden behind a comment slip through).
        if ch == "-" and i + 1 < n and text[i + 1] == "-":
            raise ValueError("comments are not allowed in predicates")
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            raise ValueError("comments are not allowed in predicates")
        if ch == "*" and i + 1 < n and text[i + 1] == "/":
            raise ValueError("comments are not allowed in predicates")
        if ch == "#":
            raise ValueError("comments are not allowed in predicates")

        # Statement separator.
        if ch == ";":
            raise ValueError("semicolons are not allowed in predicates")

        # String concatenation (SQL ``||`` and any lone pipe) / bitwise OR is
        # not part of the grammar and is a classic injection vector.
        if ch == "|" or ch == "&":
            raise ValueError("string concatenation is not allowed in predicates")

        # Quoted string literal: its entire contents are data.
        if ch == "'" or ch == '"':
            value, i = _scan_quoted(text, i, ch)
            tokens.append(("lit_str", value))
            continue

        # Numeric literal, with optional sign / decimal fraction.
        if ch.isdigit() or (
            ch == "-" and i + 1 < n and text[i + 1].isdigit()
        ):
            j = i + (1 if ch == "-" else 0)
            while j < n and text[j].isdigit():
                j += 1
            is_float = False
            if j < n and text[j] == "." and j + 1 < n and text[j + 1].isdigit():
                is_float = True
                j += 1
                while j < n and text[j].isdigit():
                    j += 1
            raw = text[i:j]
            tokens.append(("lit_num", float(raw) if is_float else int(raw)))
            i = j
            continue

        # Identifier (optionally dotted, e.g. orders.tenant_id) / keyword.
        if ch.isalpha() or ch == "_":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            while (
                j < n
                and text[j] == "."
                and j + 1 < n
                and (text[j + 1].isalpha() or text[j + 1] == "_")
            ):
                j += 1  # consume dot
                k = j + 1
                while k < n and (text[k].isalnum() or text[k] == "_"):
                    k += 1
                j = k
            tokens.append(("ident", text[i:j]))
            i = j
            continue

        two = text[i:i + 2]
        if two in _TWO_CHAR_OPS:
            tokens.append(("op", two))
            i += 2
            continue
        if ch in _ONE_CHAR_OPS:
            tokens.append(("op", ch))
            i += 1
            continue

        if ch == "(":
            tokens.append(("lparen", ch))
            i += 1
            continue
        if ch == ")":
            tokens.append(("rparen", ch))
            i += 1
            continue

        # Commas, quotes mismatch etc. all land here.
        raise ValueError(f"unexpected character {ch!r} in predicate")

    return tokens


class _Parser:
    """Recursive-descent parser for the documented predicate grammar."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def _peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def _advance(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def _is_keyword(self, word: str) -> bool:
        token = self._peek()
        return (
            token is not None
            and token[0] == "ident"
            and token[1].lower() == word
        )

    def _expect_keyword(self, word: str):
        if not self._is_keyword(word):
            token = self._peek()
            found = _token_preview(token)
            raise ValueError(f"expected {word.upper()}, found {found}")
        self.pos += 1

    def parse(self) -> dict:
        node = self._parse_or()
        if self.pos != len(self.tokens):
            raise ValueError("unexpected trailing tokens in predicate")
        return node

    def _parse_or(self) -> dict:
        args = [self._parse_and()]
        while self._is_keyword("or"):
            self.pos += 1
            args.append(self._parse_and())
        if len(args) == 1:
            return args[0]
        return {"op": "or", "args": args}

    def _parse_and(self) -> dict:
        args = [self._parse_factor()]
        while self._is_keyword("and"):
            self.pos += 1
            args.append(self._parse_factor())
        if len(args) == 1:
            return args[0]
        return {"op": "and", "args": args}

    def _parse_factor(self) -> dict:
        token = self._peek()
        if token is not None and token[0] == "lparen":
            self._advance()
            node = self._parse_or()
            closing = self._peek()
            if closing is None or closing[0] != "rparen":
                raise ValueError("mismatched parentheses in predicate")
            self._advance()
            return node
        return self._parse_comparison()

    def _parse_comparison(self) -> dict:
        field_token = self._peek()
        if field_token is None or field_token[0] != "ident":
            raise ValueError("expected a field identifier in predicate")
        self._advance()
        field = field_token[1]

        # field IS [NOT] NULL
        if self._is_keyword("is"):
            self.pos += 1
            negated = False
            if self._is_keyword("not"):
                negated = True
                self.pos += 1
            self._expect_keyword("null")
            return {
                "op": "is_not_null" if negated else "is_null",
                "field": field,
            }

        op_token = self._peek()
        if op_token is None or op_token[0] != "op":
            found = _token_preview(op_token)
            raise ValueError(f"expected comparison operator, found {found}")
        self._advance()
        op = _OP_MAP[op_token[1]]

        value = self._parse_literal()
        return {"op": op, "field": field, "value": value}

    def _parse_literal(self):
        token = self._peek()
        if token is None:
            raise ValueError("expected a literal value after comparison operator")

        kind, raw = token
        if kind == "lit_str" or kind == "lit_num":
            self._advance()
            return raw

        if kind == "ident":
            lowered = raw.lower()
            if lowered == "null":
                self._advance()
                return None
            if lowered == "true":
                self._advance()
                return True
            if lowered == "false":
                self._advance()
                return False
            raise ValueError(
                f"expected a literal value, found identifier {raw!r}"
            )

        raise ValueError(f"expected a literal value, found {_token_preview(token)}")


def _token_preview(token):
    if token is None:
        return "end of input"
    return repr(token[1])


def parse_predicate(text: str) -> dict:
    """Parse a predicate string into an AST.

    Grammar, with case-insensitive keywords:

        expr       := term (OR term)*
        term       := factor (AND factor)*
        factor     := "(" expr ")" | comparison
        comparison := IDENT (EQ | NE | LT | LE | GT | GE) literal
                    | IDENT IS NULL
                    | IDENT IS NOT NULL

    AST nodes:

        {"op": "eq" | "ne" | "lt" | "le" | "gt" | "ge",
         "field": str, "value": object}
        {"op": "is_null" | "is_not_null", "field": str}
        {"op": "and" | "or", "args": [node, ...]}

    String literals are data, never executable syntax. Concatenation,
    comments, statement separators, unknown tokens, mismatched parentheses,
    and trailing input must raise ValueError.
    """
    # Defect 09 fix / contract: tokenize strictly so that string contents are
    # data and every injection-ish construct is rejected with ValueError.
    if not isinstance(text, str):
        raise ValueError("predicate text must be a string")
    tokens = _tokenize(text)
    if not tokens:
        raise ValueError("empty predicate")
    return _Parser(tokens).parse()
