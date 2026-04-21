from pathlib import Path

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


def test_resolve_target_uses_default_before_command_inference() -> None:
    result = resolve_target(
        DiscoveredTest(name="misc", command=("/tmp/build/unit_tests",)),
        AppConfig(default_build_target="all_tests"),
    )

    assert result.target == "all_tests"


def test_resolve_target_infers_target_from_ctest_command() -> None:
    result = resolve_target(
        DiscoveredTest(name="misc", command=("/tmp/build/unit_tests", "--case", "misc")),
        AppConfig(),
    )

    assert result.target == "unit_tests"
    assert "inferred" in result.reason


def test_resolve_target_reports_unresolved_without_fallback() -> None:
    result = resolve_target(DiscoveredTest(name="misc"), AppConfig())

    assert result.target is None
    assert not result.resolved
    assert "No build target mapping" in result.reason
