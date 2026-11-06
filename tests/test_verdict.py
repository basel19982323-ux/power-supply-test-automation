"""The four results, the fixed error codes, and the overall result (rules 9 and 10)."""
import re

import pytest

import testtypes
from core.results import read_csv
from core.runner import run_test
from core.verdict import (ERROR, ERROR_CODES, FAIL, NOT_RUN, NOT_RUN_CODES, PASS,
                          combine, overall, summarize)


def rows(*results):
    return [{"result": r} for r in results]


def test_summarize_counts_all_four_results():
    assert summarize(rows(PASS, PASS, FAIL, ERROR, NOT_RUN)) == {
        "total": 5, "pass": 2, "fail": 1, "error": 1, "not_run": 1}


def test_unknown_result_is_counted_as_error_never_as_pass():
    assert summarize(rows("", "pass?", None))["pass"] == 0
    assert summarize(rows("", "pass?", None))["error"] == 3


@pytest.mark.parametrize("results, expected", [
    ((PASS, PASS), PASS),                  # PASS only if every point is PASS
    ((PASS, FAIL, ERROR, NOT_RUN), FAIL),  # any FAIL -> FAIL
    ((PASS, ERROR, NOT_RUN), ERROR),       # otherwise any ERROR -> ERROR
    ((PASS, NOT_RUN), NOT_RUN),            # otherwise any NOT RUN -> NOT RUN
    ((), NOT_RUN),                         # nothing measured is not a pass
    ((PASS, "garbage"), ERROR),            # an unknown result is never a pass
])
def test_overall_result_rules(results, expected):
    assert combine(results) == expected


def test_run_error_makes_the_run_error_unless_something_failed():
    assert overall(rows(PASS, PASS), run_error="DISCONNECTED: lost the scope") == ERROR
    assert overall(rows(PASS, FAIL), run_error="DISCONNECTED: lost the scope") == FAIL


def test_error_codes_are_fixed_short_names_with_a_meaning():
    for code, meaning in {**ERROR_CODES, **NOT_RUN_CODES}.items():
        assert re.fullmatch(r"[A-Z_]+", code), code
        assert meaning, code


@pytest.mark.parametrize("test_id", ["dynamic_output_response", "vds_turnoff", "vds_ovp"])
def test_every_row_and_csv_has_code_and_reason_columns(tmp_path, test_id):
    t = testtypes.get_test(test_id)
    res = run_test(t, t.default_config(), simulate=True, output_root=str(tmp_path))
    assert res.rows and all("error_code" in r and "reason" in r for r in res.rows)
    header = read_csv(res.csv_path)[0].keys()
    assert "error_code" in header and "reason" in header
