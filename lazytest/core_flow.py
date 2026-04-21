from __future__ import annotations

from collections.abc import Awaitable, Callable

from lazytest.cmake_build import build_target
from lazytest.config import AppConfig
from lazytest.models import DiscoveredTest, TestStatus
from lazytest.session import TestSession
from lazytest.target_resolution import resolve_target
from lazytest.test_runner import run_test

OutputCallback = Callable[[str], Awaitable[None] | None]


async def build_and_run_test(
    config: AppConfig,
    session: TestSession,
    test: DiscoveredTest,
    on_output: OutputCallback,
) -> bool:
    resolution = resolve_target(test, config)
    if not resolution.target:
        await _emit(on_output, f"{resolution.reason}\n")
        session.set_status(test.name, TestStatus.FAILED)
        return False

    session.set_status(test.name, TestStatus.RUNNING)
    await _emit(on_output, f"$ cmake --build target {resolution.target} ({resolution.reason})\n")
    build_result = await build_target(config, resolution.target, on_output)
    if not build_result.ok:
        session.set_status(test.name, TestStatus.FAILED)
        return False

    await _emit(on_output, f"$ ctest {test.name}\n")
    test_result = await run_test(config, test, on_output)
    session.set_status(test.name, TestStatus.PASSED if test_result.ok else TestStatus.FAILED)
    return test_result.ok


async def _emit(on_output: OutputCallback, text: str) -> None:
    value = on_output(text)
    if value is not None:
        await value
