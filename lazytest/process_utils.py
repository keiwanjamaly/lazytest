from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from collections.abc import Awaitable, Callable
from pathlib import Path

from lazytest.models import ProcessResult

OutputCallback = Callable[[str], Awaitable[None] | None]


async def run_streaming(
    command: list[str],
    *,
    cwd: Path | None = None,
    on_output: OutputCallback | None = None,
) -> ProcessResult:
    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )
    except FileNotFoundError as exc:
        if on_output:
            await _maybe_await(on_output(f"Executable not found: {command[0]}\n"))
        return ProcessResult(command=tuple(command), returncode=127)
    except OSError as exc:
        if on_output:
            await _maybe_await(on_output(f"Failed to start {' '.join(command)}: {exc}\n"))
        return ProcessResult(command=tuple(command), returncode=126)

    try:
        assert process.stdout is not None
        while True:
            chunk = await process.stdout.readline()
            if not chunk:
                break
            if on_output:
                await _maybe_await(on_output(chunk.decode(errors="replace")))

        returncode = await process.wait()
        return ProcessResult(command=tuple(command), returncode=returncode)
    except asyncio.CancelledError:
        await _terminate_process(process)
        raise


async def collect_command(command: list[str], *, cwd: Path | None = None) -> ProcessResultWithOutput:
    lines: list[str] = []

    async def capture(text: str) -> None:
        lines.append(text)

    result = await run_streaming(command, cwd=cwd, on_output=capture)
    return ProcessResultWithOutput(
        command=result.command,
        returncode=result.returncode,
        output="".join(lines),
    )


class ProcessResultWithOutput(ProcessResult):
    output: str

    def __init__(self, command: tuple[str, ...], returncode: int, output: str) -> None:
        super().__init__(command=command, returncode=returncode)
        object.__setattr__(self, "output", output)


async def _maybe_await(value: Awaitable[None] | None) -> None:
    if value is not None:
        await value


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return

    if os.name == "nt":
        process.terminate()
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)

    try:
        await asyncio.wait_for(process.wait(), timeout=2)
        return
    except TimeoutError:
        pass

    if process.returncode is not None:
        return

    if os.name == "nt":
        process.kill()
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)

    await process.wait()
