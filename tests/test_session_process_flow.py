import asyncio
import sys
from pathlib import Path

import pytest

from lazytest.config import AppConfig, TargetMapping
from lazytest.core_flow import build_and_run_test
from lazytest.models import DiscoveredTest, ProcessResult, TestStatus as Status
from lazytest.process_utils import run_streaming
from lazytest.session import TestSession as Session


def test_session_status_transitions() -> None:
    session = Session.from_tests([DiscoveredTest(name="unit.math")])

    assert session.tests_by_name["unit.math"].status is Status.UNKNOWN
    session.set_status("unit.math", Status.RUNNING)
    session.set_status("unit.math", Status.PASSED)

    assert session.tests_by_name["unit.math"].status is Status.PASSED


@pytest.mark.asyncio
async def test_process_error_for_missing_executable() -> None:
    output: list[str] = []

    result = await run_streaming(["definitely-not-a-real-lazytest-command"], on_output=output.append)

    assert result.returncode == 127
    assert "Executable not found" in "".join(output)


@pytest.mark.asyncio
async def test_process_cancellation_terminates_running_process(tmp_path: Path) -> None:
    marker = tmp_path / "terminated.txt"
    output: list[str] = []
    code = """
import pathlib
import signal
import sys
import time

def handle_sigterm(signum, frame):
    pathlib.Path(sys.argv[1]).write_text("terminated", encoding="utf-8")
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)
print("ready", flush=True)
time.sleep(60)
"""

    task = asyncio.create_task(
        run_streaming([sys.executable, "-c", code, str(marker)], on_output=output.append)
    )
    for _ in range(100):
        if output:
            break
        await asyncio.sleep(0.01)
    assert output == ["ready\n"]

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert marker.read_text(encoding="utf-8") == "terminated"


@pytest.mark.asyncio
async def test_integration_style_core_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    test = DiscoveredTest(name="unit.math")
    session = Session.from_tests([test])
    config = AppConfig(
        build_dir=Path("/tmp/build"),
        target_mappings=(TargetMapping("^unit\\.", "unit_tests"),),
    )
    events: list[str] = []

    async def fake_build_target(config: AppConfig, target: str, on_output):
        events.append(f"build:{target}")
        on_output("building\n")
        return ProcessResult(command=("cmake",), returncode=0)

    async def fake_run_test(config: AppConfig, test: DiscoveredTest, on_output):
        events.append(f"test:{test.name}")
        on_output("testing\n")
        return ProcessResult(command=("ctest",), returncode=0)

    monkeypatch.setattr("lazytest.core_flow.build_target", fake_build_target)
    monkeypatch.setattr("lazytest.core_flow.run_test", fake_run_test)
    output: list[str] = []

    ok = await build_and_run_test(config, session, test, output.append)

    assert ok
    assert events == ["build:unit_tests", "test:unit.math"]
    assert "building\n" in output
    assert session.tests_by_name["unit.math"].status is Status.PASSED


@pytest.mark.asyncio
async def test_core_flow_marks_failed_when_target_unresolved() -> None:
    test = DiscoveredTest(name="unknown")
    session = Session.from_tests([test])
    output: list[str] = []

    ok = await build_and_run_test(AppConfig(), session, test, output.append)

    assert not ok
    assert session.tests_by_name["unknown"].status is Status.FAILED
    assert "No build target mapping" in "".join(output)
