from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from collections.abc import Sequence

from lazytest.config import AppConfig
from lazytest.models import ProcessResult
from lazytest.process_utils import ProcessStartCallback, run_streaming

OutputCallback = Callable[[str], Awaitable[None] | None]


def build_command(config: AppConfig, targets: str | Sequence[str]) -> list[str]:
    target_names = [targets] if isinstance(targets, str) else list(targets)
    jobs = str(os.cpu_count() or 1)
    command = ["cmake", "--build"]
    if config.build_preset:
        command.extend(["--preset", config.build_preset])
    else:
        command.append(str(config.build_dir))
    command.append("--target")
    command.extend(target_names)
    command.extend(["--parallel", jobs])
    command.extend(config.extra_build_args)
    return command


async def build_targets(
    config: AppConfig,
    targets: Sequence[str],
    on_output: OutputCallback,
    on_start: ProcessStartCallback | None = None,
) -> ProcessResult:
    return await run_streaming(
        build_command(config, targets),
        cwd=None,
        on_output=on_output,
        on_start=on_start,
    )


async def build_target(
    config: AppConfig,
    target: str,
    on_output: OutputCallback,
    on_start: ProcessStartCallback | None = None,
) -> ProcessResult:
    return await build_targets(config, [target], on_output, on_start)
