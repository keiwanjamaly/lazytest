from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path


class TestStatus(str, Enum):
    UNKNOWN = "unknown"
    RUNNING = "running"
    CANCELLED = "cancelled"
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True)
class DiscoveredTest:
    name: str
    command: tuple[str, ...] = ()
    working_directory: Path | None = None
    labels: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)
    status: TestStatus = TestStatus.UNKNOWN

    def with_status(self, status: TestStatus) -> "DiscoveredTest":
        return replace(self, status=status)


@dataclass(frozen=True)
class ProcessResult:
    command: tuple[str, ...]
    returncode: int

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class TargetResolution:
    target: str | None
    reason: str

    @property
    def resolved(self) -> bool:
        return self.target is not None
