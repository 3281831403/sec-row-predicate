"""Row-level security predicate engine: the only implementation module.

The public facade re-exports the eight functions below. Every function is a
stub in the initial state and must raise NotImplementedError.
"""


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
    raise NotImplementedError("parse_predicate")


def tri_and(a: str, b: str) -> str:
    """Return three-valued conjunction of a and b.

    Inputs and outputs are exactly true, false, or unknown. False dominates;
    otherwise unknown dominates; true is the identity.
    """
    raise NotImplementedError("tri_and")


def tri_or(a: str, b: str) -> str:
    """Return three-valued disjunction of a and b.

    Inputs and outputs are exactly true, false, or unknown. True dominates;
    otherwise unknown dominates; false is the identity.
    """
    raise NotImplementedError("tri_or")


def evaluate(predicate: dict, row: dict) -> str:
    """Evaluate a predicate against one row and return true, false, or unknown.

    A missing field and a field whose value is None both count as SQL NULL.
    Any comparison involving NULL is unknown. is_null is true exactly for
    SQL NULL, and is_not_null is its complement. and and or must combine
    child results with tri_and and tri_or rather than coercing them to bool.
    """
    raise NotImplementedError("evaluate")


def admits(predicate: dict, row: dict) -> bool:
    """Return True only when evaluate returns true.

    Both false and unknown must be rejected. The return value is a bool.
    """
    raise NotImplementedError("admits")


def combine(predicates) -> dict:
    """Return one conjunction of all predicates.

    The result must be independent of input order and must remove operands
    that are structurally identical. A single distinct operand may be
    returned directly or wrapped in an and node.
    """
    raise NotImplementedError("combine")


def expand_view(view: dict, predicates) -> dict:
    """Expand a view to its effective predicate AST.

    view is a mapping with a predicate entry describing the view filter.
    predicates are predicates bound to the view's base table. The result is
    the conjunction of the view predicate and every base predicate; base
    predicates must never be dropped.
    """
    raise NotImplementedError("expand_view")


def predicate_batch(rows, policy) -> dict:
    """Evaluate policy for every row and return {row_index: bool}.

    Each row is evaluated in isolation. No NULL set, result, or other row
    context may leak from one row or one batch call to the next.
    """
    raise NotImplementedError("predicate_batch")