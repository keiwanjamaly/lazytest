from pathlib import Path

from lazytest.models import DiscoveredTest
from lazytest.search import filter_tests, preserve_selection, rank_tests


def test_search_matches_name_labels_command_and_working_directory() -> None:
    tests = [
        DiscoveredTest(name="alpha", labels=("unit",), command=("runner",), working_directory=Path("/a")),
        DiscoveredTest(name="beta", labels=("slow",), command=("db_runner",), working_directory=Path("/b")),
        DiscoveredTest(name="gamma", labels=(), command=("runner",), working_directory=Path("/special/path")),
    ]

    assert [test.name for test in filter_tests(tests, "UNIT")] == ["alpha"]
    assert [test.name for test in filter_tests(tests, "db_runner")] == ["beta"]
    assert [test.name for test in filter_tests(tests, "special")] == ["gamma"]


def test_search_ordering_is_ranked_and_stable() -> None:
    tests = [
        DiscoveredTest(name="abc_extra"),
        DiscoveredTest(name="xabc"),
        DiscoveredTest(name="abc"),
        DiscoveredTest(name="label_hit", labels=("abc",)),
        DiscoveredTest(name="cmd_hit", command=("abc",)),
    ]

    ranked = rank_tests(tests, "abc")

    assert [(item.test.name, item.rank) for item in ranked] == [
        ("abc", 0),
        ("abc_extra", 1),
        ("xabc", 2),
        ("label_hit", 3),
        ("cmd_hit", 4),
    ]


def test_preserve_selection_keeps_visible_name_or_uses_fallback() -> None:
    tests = [DiscoveredTest(name="a"), DiscoveredTest(name="b")]

    assert preserve_selection("b", tests) == 1
    assert preserve_selection("missing", tests, fallback_index=7) == 1
    assert preserve_selection("missing", []) is None
