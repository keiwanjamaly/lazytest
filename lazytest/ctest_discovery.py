from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lazytest.config import AppConfig
from lazytest.models import DiscoveredTest


def discovery_command(config: AppConfig) -> list[str]:
    command = ["ctest", "--show-only=json-v1"]
    if config.test_preset:
        command.extend(["--preset", config.test_preset])
    else:
        command.extend(["--test-dir", str(config.build_dir)])
    command.extend(config.extra_ctest_args)
    return command


def parse_ctest_json(payload: str | bytes) -> list[DiscoveredTest]:
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"CTest returned malformed JSON: {exc}") from exc

    tests = raw.get("tests", [])
    if not isinstance(tests, list):
        raise ValueError("CTest JSON field 'tests' must be a list")

    parsed: list[DiscoveredTest] = []
    for entry in tests:
        if not isinstance(entry, dict):
            continue
        test = _parse_test(entry)
        if test is not None:
            parsed.append(test)
    return parsed


def _parse_test(entry: dict[str, Any]) -> DiscoveredTest | None:
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        return None

    properties = _property_map(entry.get("properties"))
    labels = _labels_from(entry, properties)
    working_directory = _working_directory_from(entry, properties)
    command = _command_from(entry.get("command"))
    metadata = {
        key: str(value)
        for key, value in properties.items()
        if key not in {"LABELS", "WORKING_DIRECTORY"} and _is_scalar(value)
    }
    return DiscoveredTest(
        name=name,
        command=command,
        working_directory=working_directory,
        labels=labels,
        metadata=metadata,
    )


def _property_map(properties: object) -> dict[str, object]:
    result: dict[str, object] = {}
    if not isinstance(properties, list):
        return result
    for item in properties:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str):
            result[name] = item.get("value")
    return result


def _labels_from(entry: dict[str, Any], properties: dict[str, object]) -> tuple[str, ...]:
    value = entry.get("labels", properties.get("LABELS", ()))
    if isinstance(value, list):
        return tuple(str(item) for item in value if item is not None)
    if isinstance(value, str):
        return tuple(part for part in value.split(";") if part)
    return ()


def _working_directory_from(
    entry: dict[str, Any], properties: dict[str, object]
) -> Path | None:
    value = entry.get("workingDirectory", properties.get("WORKING_DIRECTORY"))
    if isinstance(value, str) and value:
        return Path(value)
    return None


def _command_from(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item) for item in value if item is not None)
    if isinstance(value, str):
        return (value,)
    return ()


def _is_scalar(value: object) -> bool:
    return isinstance(value, str | int | float | bool) or value is None
