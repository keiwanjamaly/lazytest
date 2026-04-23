from pathlib import Path

from lazytest.cmake_file_api import ExecutableArtifact, ExecutableArtifactIndex
from lazytest.config import AppConfig, TargetMapping
from lazytest.models import DiscoveredTest
from lazytest.target_resolution import resolve_target


def test_resolve_target_uses_regex_mapping_first() -> None:
    config = AppConfig(
        build_dir=Path("build"),
        default_build_target="all_tests",
        target_mappings=(TargetMapping("^unit\\.", "unit_tests"),),
    )

    result = resolve_target(DiscoveredTest(name="unit.math"), config)

    assert result.target == "unit_tests"
    assert "matched regex" in result.reason


def test_resolve_target_uses_default_target() -> None:
    result = resolve_target(
        DiscoveredTest(name="misc"),
        AppConfig(default_build_target="all_tests"),
    )

    assert result.target == "all_tests"


def test_resolve_target_uses_mapping_before_file_api() -> None:
    build_dir = Path("/tmp/build")
    result = resolve_target(
        DiscoveredTest(
            name="unit.math",
            command=("/tmp/build/unit_tests",),
            working_directory=build_dir,
        ),
        AppConfig(
            build_dir=build_dir,
            target_mappings=(TargetMapping("^unit", "mapped_unit_tests"),),
        ),
        _artifact_index(build_dir / "unit_tests", "unit_tests"),
    )

    assert result.target == "mapped_unit_tests"


def test_resolve_target_uses_default_before_file_api() -> None:
    build_dir = Path("/tmp/build")
    result = resolve_target(
        DiscoveredTest(
            name="misc",
            command=("/tmp/build/unit_tests",),
            working_directory=build_dir,
        ),
        AppConfig(build_dir=build_dir, default_build_target="all_tests"),
        _artifact_index(build_dir / "unit_tests", "unit_tests"),
    )

    assert result.target == "all_tests"


def test_resolve_target_uses_file_api_for_direct_executable_command() -> None:
    build_dir = Path("/tmp/build")
    result = resolve_target(
        DiscoveredTest(
            name="misc",
            command=("/tmp/build/unit_tests", "--case", "misc"),
            working_directory=build_dir,
        ),
        AppConfig(build_dir=build_dir),
        _artifact_index(build_dir / "unit_tests", "unit_tests"),
    )

    assert result.target == "unit_tests"
    assert "File API" in result.reason


def test_resolve_target_uses_file_api_for_bash_wrapper_command() -> None:
    build_dir = Path("/tmp/build")
    result = resolve_target(
        DiscoveredTest(
            name="wrapper",
            command=("bash", "-c", "make wrapped_tests && /tmp/build/wrapped_tests"),
            working_directory=build_dir,
        ),
        AppConfig(build_dir=build_dir),
        _artifact_index(build_dir / "wrapped_tests", "wrapped_tests"),
    )

    assert result.target == "wrapped_tests"


def test_resolve_target_uses_explicit_make_target_without_file_api_match() -> None:
    result = resolve_target(
        DiscoveredTest(
            name="wrapper",
            command=("bash", "-c", "make wrapped_tests && ./wrapped_tests"),
            working_directory=Path("/tmp/build"),
        ),
        AppConfig(build_dir=Path("/tmp/build")),
        ExecutableArtifactIndex(),
    )

    assert result.target == "wrapped_tests"
    assert "explicit build target" in result.reason


def test_resolve_target_uses_explicit_make_target_with_absolute_make_path() -> None:
    result = resolve_target(
        DiscoveredTest(
            name="wrapper",
            command=("bash", "-c", "/usr/bin/make wrapped_tests && ./wrapped_tests"),
            working_directory=Path("/tmp/build"),
        ),
        AppConfig(build_dir=Path("/tmp/build")),
        ExecutableArtifactIndex(),
    )

    assert result.target == "wrapped_tests"


def test_resolve_target_uses_explicit_cmake_build_target_without_file_api_match() -> None:
    result = resolve_target(
        DiscoveredTest(
            name="wrapper",
            command=("bash", "-c", "cmake --build . --target wrapped_tests && ./wrapped_tests"),
            working_directory=Path("/tmp/build"),
        ),
        AppConfig(build_dir=Path("/tmp/build")),
        ExecutableArtifactIndex(),
    )

    assert result.target == "wrapped_tests"


def test_resolve_target_uses_explicit_cmake_build_target_with_absolute_cmake_path() -> None:
    result = resolve_target(
        DiscoveredTest(
            name="wrapper",
            command=(
                "bash",
                "-c",
                "/opt/homebrew/bin/cmake --build . --target wrapped_tests && ./wrapped_tests",
            ),
            working_directory=Path("/tmp/build"),
        ),
        AppConfig(build_dir=Path("/tmp/build")),
        ExecutableArtifactIndex(),
    )

    assert result.target == "wrapped_tests"


def test_resolve_target_uses_absolute_wrapped_executable_path_without_file_api_match() -> None:
    result = resolve_target(
        DiscoveredTest(
            name="legacy.random.check1",
            command=(
                "/opt/homebrew/bin/mpiexec",
                "-n",
                "4",
                "/tmp/build/openqcd_devel_random_check1",
            ),
            working_directory=Path("/tmp/build/test_runs/legacy.random.check1"),
        ),
        AppConfig(build_dir=Path("/tmp/build")),
        ExecutableArtifactIndex(),
    )

    assert result.target == "openqcd_devel_random_check1"
    assert "direct CTest executable path" in result.reason


def test_resolve_target_infers_direct_executable_path_without_file_api_match() -> None:
    result = resolve_target(
        DiscoveredTest(
            name="tbb",
            command=(
                "/Users/bomel/Projects/DiFfRG_private/build/tests/common/tbb",
                "Test TBB reducer - 2",
            ),
            working_directory=Path("/Users/bomel/Projects/DiFfRG_private/build/tests/common"),
        ),
        AppConfig(build_dir=Path("/Users/bomel/Projects/DiFfRG_private/build")),
        ExecutableArtifactIndex(),
    )

    assert result.target == "tbb"
    assert "direct CTest executable path" in result.reason


def test_resolve_target_does_not_infer_bash_without_explicit_target() -> None:
    result = resolve_target(
        DiscoveredTest(
            name="wrapper",
            command=("bash", "-c", "./wrapped_tests --case wrapper"),
            working_directory=Path("/tmp/build"),
        ),
        AppConfig(build_dir=Path("/tmp/build")),
        ExecutableArtifactIndex(),
    )

    assert result.target is None
    assert not result.resolved


def test_resolve_target_reports_unresolved_without_fallback() -> None:
    result = resolve_target(DiscoveredTest(name="misc"), AppConfig())

    assert result.target is None
    assert not result.resolved
    assert "No build target mapping" in result.reason


def _artifact_index(path: Path, target: str) -> ExecutableArtifactIndex:
    return ExecutableArtifactIndex(
        (ExecutableArtifact(path=path, target=target, file_name=path.name),)
    )
