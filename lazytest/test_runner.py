from __future__ import annotations

import asyncio
import re
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from lazytest.config import AppConfig
from lazytest.models import DiscoveredTest, ProcessResult
from lazytest.process_utils import collect_command, run_streaming

OutputCallback = Callable[[str], Awaitable[None] | None]
_SUPPORTS_TESTS_FROM_FILE: bool | None = None


def ctest_command_for_names(
    config: AppConfig,
    test_names: list[str],
    *,
    tests_from_file: Path | None = None,
) -> list[str]:
    command = ["ctest"]
    if config.test_preset:
        command.extend(["--preset", config.test_preset])
    else:
        command.extend(["--test-dir", str(config.build_dir)])

    if tests_from_file is not None:
        command.extend(["--tests-from-file", str(tests_from_file)])
    else:
        # Fallback for older CTest versions. Names are escaped and anchored, but CTest
        # still treats this as regex selection, so --tests-from-file is preferred.
        exact_regex = "|".join(f"^{re.escape(name)}$" for name in test_names)
        command.extend(["-R", exact_regex])

    command.append("--output-on-failure")
    command.extend(config.extra_ctest_args)
    return command


async def run_test(
    config: AppConfig,
    test: DiscoveredTest,
    on_output: OutputCallback,
) -> ProcessResult:
    return await run_tests(config, [test], on_output)


async def run_tests(
    config: AppConfig,
    tests: list[DiscoveredTest],
    on_output: OutputCallback,
) -> ProcessResult:
    names = [test.name for test in tests]
    if not await ctest_supports_tests_from_file():
        await _emit(
            on_output,
            "CTest --tests-from-file is unavailable; using anchored regex fallback.\n",
        )
        return await run_streaming(
            ctest_command_for_names(config, names),
            cwd=None,
            on_output=on_output,
        )

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as stream:
        path = Path(stream.name)
        for name in names:
            stream.write(f"{name}\n")
    try:
        return await run_streaming(
            ctest_command_for_names(config, names, tests_from_file=path),
            cwd=None,
            on_output=on_output,
        )
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            await asyncio.sleep(0)


async def ctest_supports_tests_from_file() -> bool:
    global _SUPPORTS_TESTS_FROM_FILE
    if _SUPPORTS_TESTS_FROM_FILE is None:
        result = await collect_command(["ctest", "--help"])
        _SUPPORTS_TESTS_FROM_FILE = result.ok and "--tests-from-file" in result.output
    return _SUPPORTS_TESTS_FROM_FILE


async def _emit(on_output: OutputCallback, text: str) -> None:
    value = on_output(text)
    if value is not None:
        await value
