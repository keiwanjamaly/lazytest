from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TargetMapping:
    pattern: str
    target: str

    def __post_init__(self) -> None:
        try:
            re.compile(self.pattern)
        except re.error as exc:
            raise ValueError(f"Invalid target mapping regex {self.pattern!r}: {exc}") from exc


@dataclass(frozen=True)
class AppConfig:
    build_dir: Path = Path("build")
    test_preset: str | None = None
    build_preset: str | None = None
    default_build_target: str | None = None
    target_mappings: tuple[TargetMapping, ...] = ()
    extra_ctest_args: tuple[str, ...] = ()
    extra_build_args: tuple[str, ...] = ()

    def resolve_paths(self, base_dir: Path) -> "AppConfig":
        build_dir = self.build_dir
        if not build_dir.is_absolute():
            build_dir = (base_dir / build_dir).resolve()
        return AppConfig(
            build_dir=build_dir,
            test_preset=self.test_preset,
            build_preset=self.build_preset,
            default_build_target=self.default_build_target,
            target_mappings=self.target_mappings,
            extra_ctest_args=self.extra_ctest_args,
            extra_build_args=self.extra_build_args,
        )


def load_config(start_dir: Path | None = None) -> AppConfig:
    base_dir = (start_dir or Path.cwd()).resolve()
    local_config = base_dir / "lazytest.toml"
    pyproject = base_dir / "pyproject.toml"

    if local_config.exists():
        data = _read_toml(local_config)
        section = data.get("lazytest", data)
        return parse_config(section).resolve_paths(base_dir)

    if pyproject.exists():
        data = _read_toml(pyproject)
        section = data.get("tool", {}).get("lazytest", {})
        return parse_config(section).resolve_paths(base_dir)

    if _looks_like_ctest_build_dir(base_dir):
        return AppConfig(build_dir=Path(".")).resolve_paths(base_dir)

    return AppConfig().resolve_paths(base_dir)


def parse_config(data: dict[str, Any]) -> AppConfig:
    mappings = tuple(_parse_mapping(item) for item in data.get("target_mappings", ()))
    return AppConfig(
        build_dir=Path(str(data.get("build_dir", "build"))),
        test_preset=_optional_str(data.get("test_preset")),
        build_preset=_optional_str(data.get("build_preset")),
        default_build_target=_optional_str(data.get("default_build_target")),
        target_mappings=mappings,
        extra_ctest_args=_string_tuple(data.get("extra_ctest_args", ())),
        extra_build_args=_string_tuple(data.get("extra_build_args", ())),
    )


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _parse_mapping(data: dict[str, Any]) -> TargetMapping:
    pattern = data.get("pattern")
    target = data.get("target")
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("Each target mapping needs a non-empty 'pattern'")
    if not isinstance(target, str) or not target:
        raise ValueError("Each target mapping needs a non-empty 'target'")
    return TargetMapping(pattern=pattern, target=target)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Expected string or null, got {type(value).__name__}")
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise ValueError("Expected a list of strings")
    if not all(isinstance(item, str) for item in value):
        raise ValueError("Expected a list of strings")
    return tuple(value)


def _looks_like_ctest_build_dir(path: Path) -> bool:
    return (path / "CTestTestfile.cmake").exists() or (path / "Testing").is_dir()
