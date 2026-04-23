from __future__ import annotations

import re
import shlex
from pathlib import Path

from lazytest.cmake_file_api import ExecutableArtifactIndex
from lazytest.config import AppConfig
from lazytest.models import DiscoveredTest, TargetResolution

COMMAND_SEPARATORS = {"&&", "||", "|", ";"}
MAKE_COMMANDS = {"make", "gmake"}
MAKE_OPTIONS_WITH_ARGUMENTS = {"-C", "-f", "-I", "-j", "-l", "-W"}
NON_TARGET_EXECUTABLES = {
    "bash",
    "ctest",
    "env",
    "fish",
    "mpiexec",
    "mpirun",
    "orterun",
    "python",
    "python3",
    "sh",
    "srun",
    "zsh",
}


def resolve_target(
    test: DiscoveredTest,
    config: AppConfig,
    executable_artifacts: ExecutableArtifactIndex | None = None,
) -> TargetResolution:
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

    if executable_artifacts is not None:
        artifact = executable_artifacts.match_test_command(test, config.build_dir)
        if artifact is not None:
            return TargetResolution(
                target=artifact.target,
                reason="matched CMake File API executable artifact",
            )

    explicit_target = explicit_build_target(test)
    if explicit_target is not None:
        return TargetResolution(
            target=explicit_target,
            reason="matched explicit build target in CTest command",
        )

    direct_target = direct_executable_target(test)
    if direct_target is not None:
        return TargetResolution(
            target=direct_target,
            reason="inferred from direct CTest executable path",
        )

    return TargetResolution(
        target=None,
        reason=(
            "No build target mapping is available. Add [[tool.lazytest.target_mappings]] "
            "or set tool.lazytest.default_build_target."
        ),
    )


def explicit_build_target(test: DiscoveredTest) -> str | None:
    tokens = command_tokens(test.command)
    for index, token in enumerate(tokens):
        if token in {"--target", "-t"} and index + 1 < len(tokens):
            return _target_token(tokens[index + 1])
        if token.startswith("--target="):
            return _target_token(token.partition("=")[2])
        if _command_name(token) == "cmake" and index + 1 < len(tokens):
            target = _cmake_invocation_target(tokens[index + 1 :])
            if target is not None:
                return target
        if token == "--build":
            target = _cmake_build_target(tokens[index + 1 :])
            if target is not None:
                return target
        if _command_name(token) in MAKE_COMMANDS:
            target = _make_target(tokens[index + 1 :])
            if target is not None:
                return target
    return None


def direct_executable_target(test: DiscoveredTest) -> str | None:
    executable = discovered_executable(test)
    if executable is None:
        return None
    return Path(executable).name


def discovered_executable(test: DiscoveredTest) -> str | None:
    if not test.command:
        return None

    direct_executable = _executable_token(test.command[0], allow_relative=True)
    if direct_executable is not None:
        return direct_executable

    for token in command_tokens(test.command)[1:]:
        executable = _executable_token(token, allow_relative=False)
        if executable is not None:
            return executable
    return None


def _cmake_invocation_target(tokens: tuple[str, ...]) -> str | None:
    for index, token in enumerate(tokens):
        if token in COMMAND_SEPARATORS:
            return None
        if token == "--build":
            return _cmake_build_target(tokens[index + 1 :])
    return None


def _cmake_build_target(tokens: tuple[str, ...]) -> str | None:
    for index, token in enumerate(tokens):
        if token in COMMAND_SEPARATORS:
            return None
        if token in {"--target", "-t"} and index + 1 < len(tokens):
            return _target_token(tokens[index + 1])
        if token.startswith("--target="):
            return _target_token(token.partition("=")[2])
    return None


def _make_target(tokens: tuple[str, ...]) -> str | None:
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if token in COMMAND_SEPARATORS:
            return None
        if token in MAKE_OPTIONS_WITH_ARGUMENTS:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        target = _target_token(token)
        if target is not None:
            return target
    return None


def _target_token(token: str) -> str | None:
    if not token or token in COMMAND_SEPARATORS:
        return None
    if token.startswith("-") or "=" in token:
        return None
    return token


def _command_name(token: str) -> str:
    return Path(token).name


def command_tokens(command: tuple[str, ...]) -> tuple[str, ...]:
    tokens = list(command)
    for argument in command:
        try:
            split = shlex.split(argument)
        except ValueError:
            continue
        if len(split) > 1:
            tokens.extend(split)
    return tuple(tokens)


def _executable_token(token: str, *, allow_relative: bool) -> str | None:
    if not token or token in COMMAND_SEPARATORS or token.startswith("-"):
        return None

    path = Path(token)
    name = path.name
    if not name or name in NON_TARGET_EXECUTABLES:
        return None
    if path.is_absolute():
        return str(path)
    if allow_relative and ("/" in token or "\\" in token):
        return str(path)
    return None
