from __future__ import annotations

import re
from pathlib import Path

from lazytest.config import AppConfig
from lazytest.models import DiscoveredTest, TargetResolution


def resolve_target(test: DiscoveredTest, config: AppConfig) -> TargetResolution:
    for mapping in config.target_mappings:
        if re.search(mapping.pattern, test.name):
            return TargetResolution(
                target=mapping.target,
                reason=f"matched regex {mapping.pattern!r}",
            )

    if config.default_build_target:
        return TargetResolution(
            target=config.default_build_target,
            reason="using configured default_build_target",
        )

    if test.command:
        inferred_target = Path(test.command[0]).name
        if inferred_target:
            return TargetResolution(
                target=inferred_target,
                reason="inferred from CTest command executable",
            )

    return TargetResolution(
        target=None,
        reason=(
            "No build target mapping is available. Add [[tool.lazytest.target_mappings]] "
            "or set tool.lazytest.default_build_target."
        ),
    )
