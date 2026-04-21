from __future__ import annotations

from dataclasses import dataclass

from lazytest.models import DiscoveredTest


@dataclass(frozen=True)
class RankedTest:
    test: DiscoveredTest
    rank: int
    original_index: int


def filter_tests(tests: list[DiscoveredTest], query: str) -> list[DiscoveredTest]:
    ranked = rank_tests(tests, query)
    return [item.test for item in ranked]


def rank_tests(tests: list[DiscoveredTest], query: str) -> list[RankedTest]:
    needle = query.strip().casefold()
    if not needle:
        return [RankedTest(test=test, rank=0, original_index=index) for index, test in enumerate(tests)]

    ranked: list[RankedTest] = []
    for index, test in enumerate(tests):
        rank = _rank(test, needle)
        if rank is not None:
            ranked.append(RankedTest(test=test, rank=rank, original_index=index))
    return sorted(ranked, key=lambda item: (item.rank, item.original_index))


def preserve_selection(
    previous_name: str | None, visible_tests: list[DiscoveredTest], fallback_index: int = 0
) -> int | None:
    if not visible_tests:
        return None
    if previous_name:
        for index, test in enumerate(visible_tests):
            if test.name == previous_name:
                return index
    return max(0, min(fallback_index, len(visible_tests) - 1))


def _rank(test: DiscoveredTest, needle: str) -> int | None:
    name = test.name.casefold()
    if name == needle:
        return 0
    if name.startswith(needle):
        return 1
    if needle in name:
        return 2
    if any(needle in label.casefold() for label in test.labels):
        return 3
    command = " ".join(test.command).casefold()
    if command and needle in command:
        return 4
    if test.working_directory and needle in str(test.working_directory).casefold():
        return 5
    if any(needle in value.casefold() for value in test.metadata.values()):
        return 6
    return None
