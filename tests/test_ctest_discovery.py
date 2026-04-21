from pathlib import Path

import pytest

from lazytest.ctest_discovery import parse_ctest_json
from tests.fixtures import SAMPLE_CTEST_JSON


def test_parse_ctest_json_discovers_tests() -> None:
    tests = parse_ctest_json(SAMPLE_CTEST_JSON)

    assert [test.name for test in tests] == [
        "unit.math.addition",
        "integration.database",
        "misc.no_metadata",
    ]
    assert tests[0].command == ("/tmp/build/unit_tests", "unit.math.addition")
    assert tests[0].labels == ("unit", "fast")
    assert tests[0].working_directory == Path("/tmp/build")
    assert tests[1].labels == ("integration", "slow")


def test_parse_ctest_json_skips_entries_without_names() -> None:
    tests = parse_ctest_json('{"tests": [{"command": ["x"]}, {"name": "ok"}]}')

    assert [test.name for test in tests] == ["ok"]


def test_parse_ctest_json_rejects_malformed_payload() -> None:
    with pytest.raises(ValueError, match="malformed JSON"):
        parse_ctest_json("{")


def test_parse_ctest_json_rejects_non_list_tests_field() -> None:
    with pytest.raises(ValueError, match="must be a list"):
        parse_ctest_json('{"tests": {}}')
