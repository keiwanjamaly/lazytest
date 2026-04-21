from rich.text import Text
import pytest

from lazytest.app import LazytestApp
from lazytest.config import AppConfig
from lazytest.models import DiscoveredTest, ProcessResult, TestStatus as Status
from lazytest.session import TestSession as Session


def test_format_test_uses_colored_status_markers() -> None:
    app = LazytestApp(AppConfig())

    assert app.format_test(DiscoveredTest("not.run")) == "[dim]○ not.run[/]"
    assert app.format_test(DiscoveredTest("active", status=Status.RUNNING)) == "[yellow]⟳ active[/]"
    assert app.format_test(DiscoveredTest("ok", status=Status.PASSED)) == "[green]✓ ok[/]"
    assert app.format_test(DiscoveredTest("bad", status=Status.FAILED)) == "[red]✗ bad[/]"


def test_format_test_escapes_markup_in_test_names_and_labels() -> None:
    app = LazytestApp(AppConfig())
    formatted = app.format_test(
        DiscoveredTest(
            "case[brackets]",
            labels=("unit[fast]",),
            status=Status.PASSED,
        )
    )

    assert Text.from_markup(formatted).plain == "✓ case[brackets] [unit[fast]]"


def test_group_tests_by_executable_uses_ctest_command_executable() -> None:
    app = LazytestApp(AppConfig())
    tests = [
        DiscoveredTest("a", command=("/tmp/build/unit_tests", "a")),
        DiscoveredTest("b", command=("/tmp/build/unit_tests", "b")),
        DiscoveredTest("c", command=("/tmp/build/integration_tests", "c")),
    ]

    groups = app.group_tests_by_executable(tests)

    assert list(groups) == ["unit_tests", "integration_tests"]
    assert [test.name for test in groups["unit_tests"]] == ["a", "b"]


@pytest.mark.asyncio
async def test_run_tests_by_name_builds_target_once_and_runs_tests_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = LazytestApp(AppConfig(default_build_target="unit_tests"))
    app.session = Session.from_tests(
        [
            DiscoveredTest("unit.math.addition"),
            DiscoveredTest("unit.math.subtraction"),
        ]
    )
    refreshed_statuses: list[Status] = []
    events: list[str] = []
    output: dict[str, list[str]] = {}

    async def fake_refresh_test_status(name: str) -> None:
        refreshed_statuses.append(app.session.tests_by_name[name].status)

    async def fake_build_target(config, target, on_output):
        events.append(f"build:{target}")
        return ProcessResult(command=("cmake",), returncode=0)

    async def fake_run_test(config, test, on_output):
        events.append(f"test:{test.name}")
        await on_output(f"output from {test.name}\n")
        return ProcessResult(command=("ctest",), returncode=0)

    async def fake_append_output(text: str, *, key: str = "session") -> None:
        output.setdefault(key, []).append(text)

    monkeypatch.setattr(app, "refresh_test_status", fake_refresh_test_status)
    monkeypatch.setattr(app, "show_output", lambda key: None)
    monkeypatch.setattr(app, "append_output", fake_append_output)
    monkeypatch.setattr("lazytest.app.build_target", fake_build_target)
    monkeypatch.setattr("lazytest.app.run_test", fake_run_test)

    await app._run_tests_by_name(["unit.math.addition", "unit.math.subtraction"])

    assert events == [
        "build:unit_tests",
        "test:unit.math.addition",
        "test:unit.math.subtraction",
    ]
    assert refreshed_statuses == [Status.RUNNING, Status.PASSED, Status.PASSED]
    assert "".join(output["session"]) == "$ cmake --build target unit_tests (using configured default_build_target)\n"
    assert "".join(output["test:unit.math.addition"]) == (
        "$ ctest unit.math.addition\n"
        "output from unit.math.addition\n"
    )
    assert "".join(output["test:unit.math.subtraction"]) == (
        "$ ctest unit.math.subtraction\n"
        "output from unit.math.subtraction\n"
    )
