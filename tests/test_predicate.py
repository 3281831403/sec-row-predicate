"""Strict specification tests for the row-level security predicate engine.

The initial eight stubs all raise NotImplementedError, so every test is red.
Do not modify this file while fixing rls/_impl.py.
"""

from copy import deepcopy

import pytest

from rls import (
    admits,
    combine,
    evaluate,
    expand_view,
    parse_predicate,
    predicate_batch,
    tri_and,
    tri_or,
)


TENANT = {"op": "eq", "field": "tenant_id", "value": 7}
REGION = {"op": "eq", "field": "region", "value": "eu"}


def _leaf_count(predicate):
    if predicate["op"] in {"and", "or"}:
        return sum(_leaf_count(child) for child in predicate["args"])
    return 1


def test_defect_01_tri_and_keeps_unknown():
    assert tri_and("true", "true") == "true"
    assert tri_and("true", "false") == "false"
    assert tri_and("false", "true") == "false"
    assert tri_and("false", "false") == "false"
    assert tri_and("unknown", "true") == "unknown"
    assert tri_and("true", "unknown") == "unknown"
    assert tri_and("unknown", "unknown") == "unknown"
    assert tri_and("unknown", "false") == "false"
    assert tri_and("false", "unknown") == "false"


def test_defect_02_tri_or_keeps_unknown():
    assert tri_or("true", "true") == "true"
    assert tri_or("true", "false") == "true"
    assert tri_or("false", "true") == "true"
    assert tri_or("false", "false") == "false"
    assert tri_or("unknown", "false") == "unknown"
    assert tri_or("false", "unknown") == "unknown"
    assert tri_or("unknown", "unknown") == "unknown"
    assert tri_or("unknown", "true") == "true"
    assert tri_or("true", "unknown") == "true"


def test_defect_03_evaluate_preserves_unknown():
    assert evaluate(TENANT, {"tenant_id": 7}) == "true"
    assert evaluate(TENANT, {"tenant_id": 8}) == "false"
    assert evaluate(TENANT, {"tenant_id": None}) == "unknown"
    assert evaluate(TENANT, {}) == "unknown"
    assert evaluate({"op": "ne", "field": "tenant_id", "value": 7}, {"tenant_id": None}) == "unknown"


def test_defect_04_admits_rejects_unknown():
    assert admits(TENANT, {"tenant_id": 7}) is True
    assert admits(TENANT, {"tenant_id": 8}) is False
    assert admits(TENANT, {"tenant_id": None}) is False
    assert admits(TENANT, {}) is False


def test_defect_05_null_equality_is_unknown():
    equals_null = {"op": "eq", "field": "owner", "value": None}
    not_equals_null = {"op": "ne", "field": "owner", "value": None}
    assert evaluate(equals_null, {"owner": None}) == "unknown"
    assert evaluate(equals_null, {"owner": "alice"}) == "unknown"
    assert evaluate(equals_null, {}) == "unknown"
    assert evaluate(not_equals_null, {"owner": None}) == "unknown"
    assert admits(equals_null, {"owner": None}) is False


def test_defect_06_combine_short_circuit_is_order_independent():
    unknown_predicate = {"op": "eq", "field": "region", "value": "eu"}
    false_predicate = {"op": "eq", "field": "tenant_id", "value": 8}
    row = {"tenant_id": 9}
    unknown_then_false = combine([unknown_predicate, false_predicate])
    false_then_unknown = combine([false_predicate, unknown_predicate])
    assert evaluate(unknown_then_false, row) == "false"
    assert evaluate(false_then_unknown, row) == "false"
    assert admits(unknown_then_false, row) is False
    assert admits(false_then_unknown, row) is False
    raw_unknown_then_false = {"op": "and", "args": [unknown_predicate, false_predicate]}
    raw_false_then_unknown = {"op": "and", "args": [false_predicate, unknown_predicate]}
    assert evaluate(raw_unknown_then_false, row) == "false"
    assert evaluate(raw_false_then_unknown, row) == "false"


def test_defect_07_combine_deduplicates_predicates():
    score = {"op": "gt", "field": "score", "value": 10}
    duplicated = combine([TENANT, deepcopy(TENANT), TENANT])
    assert _leaf_count(duplicated) == 1
    row = {"tenant_id": 7, "score": 11}
    assert evaluate(duplicated, row) == "true"
    assert admits(duplicated, row) is True
    pair = combine([TENANT, score])
    assert _leaf_count(pair) == 2
    assert evaluate(pair, row) == "true"


def test_defect_08_view_expansion_keeps_base_predicate():
    view = {
        "name": "v_orders",
        "base": "orders",
        "predicate": {"op": "gt", "field": "amount", "value": 0},
    }
    base_predicates = [TENANT, REGION]
    expanded = expand_view(view, base_predicates)
    assert admits(expanded, {"tenant_id": 7, "region": "eu", "amount": 10}) is True
    assert admits(expanded, {"tenant_id": 8, "region": "eu", "amount": 10}) is False
    assert admits(expanded, {"tenant_id": 7, "region": "us", "amount": 10}) is False
    assert admits(expanded, {"tenant_id": 7, "region": "eu", "amount": 0}) is False
    assert admits(expanded, {"tenant_id": 7, "region": None, "amount": 10}) is False


def test_defect_09_parser_rejects_string_concatenation():
    parsed = parse_predicate("tenant_id = '7 OR tenant_id = 8'")
    assert parsed == {
        "op": "eq",
        "field": "tenant_id",
        "value": "7 OR tenant_id = 8",
    }
    with pytest.raises(ValueError):
        parse_predicate("tenant_id = 7 || ' OR tenant_id = 8'")


def test_defect_10_batch_rows_are_independent():
    policy = {"op": "and", "args": [TENANT, REGION]}
    rows = [
        {"tenant_id": 7, "region": None},
        {"tenant_id": 7, "region": "eu"},
        {"tenant_id": 8, "region": "eu"},
    ]
    assert predicate_batch(rows, policy) == {0: False, 1: True, 2: False}


def test_true_predicate_admits():
    predicate = {"op": "gt", "field": "score", "value": 10}
    assert admits(predicate, {"score": 11}) is True


def test_false_predicate_rejects():
    predicate = {"op": "gt", "field": "score", "value": 10}
    assert admits(predicate, {"score": 10}) is False


def test_unknown_predicate_rejects():
    predicate = {"op": "gt", "field": "score", "value": 10}
    assert admits(predicate, {"score": None}) is False
    assert admits(predicate, {}) is False


def test_combine_order_does_not_change_result():
    first = combine([TENANT, REGION])
    second = combine([REGION, TENANT])
    rows = [
        {"tenant_id": 7, "region": "eu"},
        {"tenant_id": 8, "region": "eu"},
        {"tenant_id": 7, "region": "us"},
        {"tenant_id": 7, "region": None},
    ]
    expected = [True, False, False, False]
    for row, expected_result in zip(rows, expected):
        assert evaluate(first, row) == evaluate(second, row)
        assert admits(first, row) is expected_result
        assert admits(second, row) is expected_result


def test_separate_batches_match_individual_rows():
    policy = {"op": "and", "args": [TENANT, REGION]}
    rows = [
        {"tenant_id": 7, "region": "eu"},
        {"tenant_id": 8, "region": "eu"},
        {"tenant_id": 7, "region": None},
        {"tenant_id": 7, "region": "us"},
    ]
    first = predicate_batch(rows, policy)
    second = predicate_batch(rows, policy)
    individual = {index: admits(policy, row) for index, row in enumerate(rows)}
    assert first == individual
    assert second == individual
    assert first == {0: True, 1: False, 2: False, 3: False}