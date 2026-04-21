from __future__ import annotations

from dataclasses import dataclass, field

from lazytest.models import DiscoveredTest, TestStatus


@dataclass
class TestSession:
    tests_by_name: dict[str, DiscoveredTest] = field(default_factory=dict)

    @classmethod
    def from_tests(cls, tests: list[DiscoveredTest]) -> "TestSession":
        return cls(tests_by_name={test.name: test for test in tests})

    @property
    def tests(self) -> list[DiscoveredTest]:
        return list(self.tests_by_name.values())

    def set_status(self, test_name: str, status: TestStatus) -> None:
        test = self.tests_by_name[test_name]
        self.tests_by_name[test_name] = test.with_status(status)

    def failed_tests(self) -> list[DiscoveredTest]:
        return [test for test in self.tests if test.status is TestStatus.FAILED]
