from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from lazytest.config import AppConfig
from lazytest.models import ProcessResult
from lazytest.process_utils import run_streaming

OutputCallback = Callable[[str], Awaitable[None] | None]


def build_command(config: AppConfig, target: str) -> list[str]:
    jobs = str(os.cpu_count() or 1)
    command = ["cmake", "--build"]
    if config.build_preset:
        command.extend(["--preset", config.build_preset])
    else:
        command.append(str(config.build_dir))
    command.extend(["--target", target, "--parallel", jobs])
    command.extend(config.extra_build_args)
    return command


async def build_target(
    config: AppConfig, target: str, on_output: OutputCallback
) -> ProcessResult:
    return await run_streaming(build_command(config, target), cwd=None, on_output=on_output)
