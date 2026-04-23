from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lazytest.cmake_file_api import load_executable_artifacts
from lazytest.config import AppConfig
from lazytest.ctest_discovery import parse_ctest_json
from lazytest.target_resolution import resolve_target


def test_cmake_file_api_resolves_bash_wrapped_ctest_target(tmp_path: Path) -> None:
    if shutil.which("cmake") is None or shutil.which("ctest") is None:
        pytest.skip("cmake or ctest is unavailable")

    source_dir = tmp_path / "source"
    build_dir = tmp_path / "build"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        """
cmake_minimum_required(VERSION 3.20)
project(LazytestWrapper C)

file(WRITE "${CMAKE_BINARY_DIR}/main.c" "int main(void) { return 0; }\\n")
add_executable(test-wrapper-case "${CMAKE_BINARY_DIR}/main.c")

enable_testing()
add_test(
  NAME test-wrapper-case
  COMMAND bash -c "make test-wrapper-case && $<TARGET_FILE:test-wrapper-case>"
)
""".lstrip(),
        encoding="utf-8",
    )
    query_dir = build_dir / ".cmake" / "api" / "v1" / "query"
    query_dir.mkdir(parents=True)
    (query_dir / "codemodel-v2").touch()

    configure = subprocess.run(
        ["cmake", "-S", str(source_dir), "-B", str(build_dir)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if configure.returncode != 0:
        pytest.skip(f"cmake configure failed: {configure.stdout}")

    ctest = subprocess.run(
        ["ctest", "--show-only=json-v1", "--test-dir", str(build_dir)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    tests = parse_ctest_json(ctest.stdout)
    assert len(tests) == 1
    test = tests[0]
    assert Path(test.command[0]).name == "bash"

    artifacts = load_executable_artifacts(build_dir)
    resolution = resolve_target(test, AppConfig(build_dir=build_dir), artifacts)

    assert resolution.target == "test-wrapper-case"


def test_bash_wrapped_ctest_target_resolves_without_file_api(tmp_path: Path) -> None:
    if shutil.which("cmake") is None or shutil.which("ctest") is None:
        pytest.skip("cmake or ctest is unavailable")

    source_dir = tmp_path / "source"
    build_dir = tmp_path / "build"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        """
cmake_minimum_required(VERSION 3.20)
project(LazytestWrapperNoFileApi C)

file(WRITE "${CMAKE_BINARY_DIR}/main.c" "int main(void) { return 0; }\\n")
add_executable(test-wrapper-case "${CMAKE_BINARY_DIR}/main.c")

enable_testing()
add_test(
  NAME test-wrapper-case
  COMMAND bash -c "make test-wrapper-case && $<TARGET_FILE:test-wrapper-case>"
)
""".lstrip(),
        encoding="utf-8",
    )

    configure = subprocess.run(
        ["cmake", "-S", str(source_dir), "-B", str(build_dir)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if configure.returncode != 0:
        pytest.skip(f"cmake configure failed: {configure.stdout}")

    ctest = subprocess.run(
        ["ctest", "--show-only=json-v1", "--test-dir", str(build_dir)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    tests = parse_ctest_json(ctest.stdout)
    assert len(tests) == 1
    test = tests[0]
    assert Path(test.command[0]).name == "bash"

    resolution = resolve_target(test, AppConfig(build_dir=build_dir))

    assert resolution.target == "test-wrapper-case"
