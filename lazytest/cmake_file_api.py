from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from lazytest.models import DiscoveredTest


@dataclass(frozen=True)
class ExecutableArtifact:
    path: Path
    target: str
    file_name: str


@dataclass(frozen=True)
class ExecutableArtifactIndex:
    artifacts: tuple[ExecutableArtifact, ...] = ()

    def __post_init__(self) -> None:
        by_path = {_normalize_path(artifact.path): artifact for artifact in self.artifacts}
        object.__setattr__(self, "_by_path", by_path)

    def match_test_command(
        self, test: DiscoveredTest, build_dir: Path
    ) -> ExecutableArtifact | None:
        for token in _command_tokens(test.command):
            artifact = self.match_token(
                token,
                working_directory=test.working_directory,
                build_dir=build_dir,
            )
            if artifact is not None:
                return artifact
        return None

    def match_token(
        self,
        token: str,
        *,
        working_directory: Path | None,
        build_dir: Path,
    ) -> ExecutableArtifact | None:
        if not token or token in {"&&", "||", "|", ";"}:
            return None

        path = Path(token)
        if path.is_absolute():
            candidates = (path,)
        else:
            bases = _unique_paths(
                base for base in (working_directory, build_dir) if base is not None
            )
            candidates = tuple(base / path for base in bases)

        for candidate in candidates:
            artifact = self._by_path.get(_normalize_path(candidate))
            if artifact is not None:
                return artifact
        return None


def load_executable_artifacts(
    build_dir: Path,
    tests: Iterable[DiscoveredTest] = (),
) -> ExecutableArtifactIndex:
    reply_dir = build_dir / ".cmake" / "api" / "v1" / "reply"
    index_file = _latest_index_file(reply_dir)
    if index_file is None:
        return ExecutableArtifactIndex()

    index = _read_json(index_file)
    if index is None:
        return ExecutableArtifactIndex()

    codemodel_file = _codemodel_file(index, reply_dir)
    if codemodel_file is None:
        return ExecutableArtifactIndex()

    codemodel = _read_json(codemodel_file)
    if codemodel is None:
        return ExecutableArtifactIndex()

    candidate_names = _candidate_target_names(tests)
    target_files = _target_files(codemodel, reply_dir, candidate_names)
    artifact_groups: dict[str, list[ExecutableArtifact]] = {}
    for target_file in target_files:
        target = _read_json(target_file)
        if target is None or target.get("type") != "EXECUTABLE":
            continue
        target_name = target.get("name")
        if not isinstance(target_name, str) or not target_name:
            continue
        for artifact_path in _artifact_paths(target):
            path = _resolve_artifact_path(artifact_path, build_dir)
            artifact = ExecutableArtifact(
                path=path,
                target=target_name,
                file_name=path.name,
            )
            artifact_groups.setdefault(_normalize_path(path), []).append(artifact)

    artifacts = tuple(items[0] for items in artifact_groups.values() if len(items) == 1)
    return ExecutableArtifactIndex(artifacts)


def _latest_index_file(reply_dir: Path) -> Path | None:
    try:
        files = tuple(reply_dir.glob("index-*.json"))
    except OSError:
        return None
    if not files:
        return None
    return max(files, key=lambda path: path.name)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _codemodel_file(index: dict[str, Any], reply_dir: Path) -> Path | None:
    reply = index.get("reply")
    if not isinstance(reply, dict):
        return None
    for key, value in reply.items():
        if key.startswith("codemodel") and isinstance(value, dict):
            json_file = value.get("jsonFile")
            if isinstance(json_file, str) and json_file:
                return reply_dir / json_file
    return None


def _target_files(
    codemodel: dict[str, Any],
    reply_dir: Path,
    candidate_names: set[str],
) -> tuple[Path, ...]:
    files: list[Path] = []
    configurations = codemodel.get("configurations")
    if not isinstance(configurations, list):
        return ()
    for configuration in configurations:
        if not isinstance(configuration, dict):
            continue
        targets = configuration.get("targets")
        if not isinstance(targets, list):
            continue
        for target in targets:
            if not isinstance(target, dict):
                continue
            json_file = target.get("jsonFile")
            name = target.get("name")
            if candidate_names and name not in candidate_names:
                continue
            if isinstance(json_file, str) and json_file:
                files.append(reply_dir / json_file)
    return tuple(files)


def _artifact_paths(target: dict[str, Any]) -> tuple[str, ...]:
    artifacts = target.get("artifacts")
    if not isinstance(artifacts, list):
        return ()
    paths: list[str] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        path = artifact.get("path")
        if isinstance(path, str) and path:
            paths.append(path)
    return tuple(paths)


def _resolve_artifact_path(path: str, build_dir: Path) -> Path:
    artifact_path = Path(path)
    if artifact_path.is_absolute():
        return artifact_path.resolve(strict=False)
    return (build_dir / artifact_path).resolve(strict=False)


def _normalize_path(path: Path) -> str:
    return str(path.expanduser().resolve(strict=False))


def _unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = _normalize_path(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return tuple(unique)


def _candidate_target_names(tests: Iterable[DiscoveredTest]) -> set[str]:
    names: set[str] = set()
    for test in tests:
        for token in _command_tokens(test.command):
            if not token or token in {"&&", "||", "|", ";"}:
                continue
            basename = Path(token).name
            if basename:
                names.add(basename)
    return names


def _command_tokens(command: tuple[str, ...]) -> tuple[str, ...]:
    tokens = list(command)
    for argument in command:
        try:
            split = shlex.split(argument)
        except ValueError:
            continue
        if len(split) > 1:
            tokens.extend(split)
    return tuple(tokens)
