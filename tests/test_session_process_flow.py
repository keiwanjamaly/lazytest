import asyncio
import sys
from pathlib import Path

import pytest

from lazytest.models import DiscoveredTest, TestStatus as Status
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
async def test_process_streams_partial_output_before_exit() -> None:
    output: list[str] = []
    code = """
import sys
import time

sys.stdout.write("step 1")
sys.stdout.flush()
time.sleep(0.2)
sys.stdout.write("\\n")
sys.stdout.flush()
"""

    task = asyncio.create_task(
        run_streaming([sys.executable, "-c", code], on_output=output.append)
    )
    for _ in range(100):
        if output:
            break
        await asyncio.sleep(0.01)

    assert output == ["step 1"]
    result = await task
    assert result.ok
    assert "".join(output) == "step 1\n"


@pytest.mark.asyncio
async def test_process_reports_pid_on_start() -> None:
    pids: list[int] = []
    output: list[str] = []
    code = "import os; print(os.getpid())"

    result = await run_streaming(
        [sys.executable, "-c", code],
        on_output=output.append,
        on_start=pids.append,
    )

    assert result.ok
    assert pids == [int("".join(output).strip())]

