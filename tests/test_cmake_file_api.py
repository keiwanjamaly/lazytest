from __future__ import annotations

import json
from pathlib import Path

from lazytest.cmake_file_api import load_executable_artifacts
from lazytest.models import DiscoveredTest


def test_file_api_resolves_relative_executable_artifact(tmp_path: Path) -> None:
    _write_file_api_reply(
        tmp_path,
        targets=[
            {
                "name": "unit_tests",
                "type": "EXECUTABLE",
                "artifacts": [{"path": "tests/unit_tests"}],
            }
        ],
    )

    index = load_executable_artifacts(tmp_path)

    artifact = index.match_test_command(
        DiscoveredTest(
            "unit",
            command=("tests/unit_tests",),
            working_directory=tmp_path,
        ),
        tmp_path,
    )
    assert artifact is not None
    assert artifact.path == (tmp_path / "tests" / "unit_tests").resolve()
    assert artifact.target == "unit_tests"
    assert artifact.file_name == "unit_tests"


def test_file_api_ignores_non_executable_targets(tmp_path: Path) -> None:
    _write_file_api_reply(
        tmp_path,
        targets=[
            {
                "name": "helper",
                "type": "STATIC_LIBRARY",
                "artifacts": [{"path": "libhelper.a"}],
            }
        ],
    )

    index = load_executable_artifacts(tmp_path)

    assert (
        index.match_test_command(
            DiscoveredTest("helper", command=("libhelper.a",), working_directory=tmp_path),
            tmp_path,
        )
        is None
    )


def test_file_api_treats_duplicate_artifact_paths_as_ambiguous(tmp_path: Path) -> None:
    _write_file_api_reply(
        tmp_path,
        targets=[
            {
                "name": "first",
                "type": "EXECUTABLE",
                "artifacts": [{"path": "bin/check"}],
            },
            {
                "name": "second",
                "type": "EXECUTABLE",
                "artifacts": [{"path": "bin/check"}],
            },
        ],
    )

    index = load_executable_artifacts(tmp_path)

    assert (
        index.match_test_command(
            DiscoveredTest("check", command=("bin/check",), working_directory=tmp_path),
            tmp_path,
        )
        is None
    )


def test_file_api_missing_or_stale_replies_are_empty(tmp_path: Path) -> None:
    assert load_executable_artifacts(tmp_path).artifacts == ()

    reply_dir = tmp_path / ".cmake" / "api" / "v1" / "reply"
    reply_dir.mkdir(parents=True)
    (reply_dir / "index-0000.json").write_text(
        json.dumps(
            {
                "reply": {
                    "codemodel-v2": {
                        "kind": "codemodel",
                        "jsonFile": "missing-codemodel.json",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    assert load_executable_artifacts(tmp_path).artifacts == ()


def test_file_api_matches_shell_command_tokens(tmp_path: Path) -> None:
    _write_file_api_reply(
        tmp_path,
        targets=[
            {
                "name": "test-wrapper-case",
                "type": "EXECUTABLE",
                "artifacts": [{"path": "test-wrapper-case"}],
            }
        ],
    )

    index = load_executable_artifacts(tmp_path)

    artifact = index.match_test_command(
        DiscoveredTest(
            "test-wrapper-case",
            command=("bash", "-c", f"make test-wrapper-case && {tmp_path / 'test-wrapper-case'}"),
            working_directory=tmp_path,
        ),
        tmp_path,
    )
    assert artifact is not None
    assert artifact.target == "test-wrapper-case"


def test_file_api_reads_only_candidate_target_replies_when_tests_are_provided(
    tmp_path: Path,
) -> None:
    targets: list[dict[str, object]] = [
        {
            "name": "wanted",
            "type": "EXECUTABLE",
            "artifacts": [{"path": "wanted"}],
        }
    ]
    targets.extend(
        {
            "name": f"irrelevant_{index}",
            "type": "EXECUTABLE",
            "artifacts": [{"path": f"irrelevant_{index}"}],
        }
        for index in range(50)
    )
    _write_file_api_reply(tmp_path, targets=targets)
    for index in range(50):
        target_file = (
            tmp_path
            / ".cmake"
            / "api"
            / "v1"
            / "reply"
            / f"target-{index + 1}.json"
        )
        target_file.write_text("{", encoding="utf-8")

    index = load_executable_artifacts(
        tmp_path,
        [DiscoveredTest("wanted", command=("bash", "-c", f"make wanted && {tmp_path / 'wanted'}"))],
    )

    assert [artifact.target for artifact in index.artifacts] == ["wanted"]


def _write_file_api_reply(build_dir: Path, *, targets: list[dict[str, object]]) -> None:
    reply_dir = build_dir / ".cmake" / "api" / "v1" / "reply"
    reply_dir.mkdir(parents=True)
    target_entries = []
    for index, target in enumerate(targets):
        target_file = f"target-{index}.json"
        (reply_dir / target_file).write_text(json.dumps(target), encoding="utf-8")
        target_entries.append({"name": target.get("name"), "jsonFile": target_file})
    (reply_dir / "codemodel-v2.json").write_text(
        json.dumps({"configurations": [{"targets": target_entries}]}),
        encoding="utf-8",
    )
    (reply_dir / "index-0000.json").write_text(
        json.dumps(
            {
                "reply": {
                    "codemodel-v2": {
                        "kind": "codemodel",
                        "jsonFile": "codemodel-v2.json",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
