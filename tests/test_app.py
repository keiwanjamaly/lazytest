from rich.text import Text
import pytest
from textual.widgets import Tree

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

    async def fake_refresh_test_statuses(names: list[str]) -> None:
        refreshed_statuses.extend(app.session.tests_by_name[name].status for name in names)

    async def fake_build_targets(config, targets, on_output):
        events.append(f"build:{','.join(targets)}")
        return ProcessResult(command=("cmake",), returncode=0)

    async def fake_run_test(config, test, on_output):
        events.append(f"test:{test.name}")
        await on_output(f"output from {test.name}\n")
        return ProcessResult(command=("ctest",), returncode=0)

    async def fake_append_output(text: str, *, key: str = "session") -> None:
        output.setdefault(key, []).append(text)

    monkeypatch.setattr(app, "refresh_test_statuses", fake_refresh_test_statuses)
    monkeypatch.setattr(app, "show_output", lambda key: None)
    monkeypatch.setattr(app, "append_output", fake_append_output)
    monkeypatch.setattr("lazytest.app.build_targets", fake_build_targets)
    monkeypatch.setattr("lazytest.app.run_test", fake_run_test)

    await app._run_tests_by_name(["unit.math.addition", "unit.math.subtraction"])

    assert events == [
        "build:unit_tests",
        "test:unit.math.addition",
        "test:unit.math.subtraction",
    ]
    assert refreshed_statuses == [
        Status.RUNNING,
        Status.RUNNING,
        Status.PASSED,
        Status.PASSED,
    ]
    assert "".join(output["session"]) == "$ cmake --build target unit_tests (using configured default_build_target)\n"
    assert "".join(output["test:unit.math.addition"]) == (
        "$ ctest unit.math.addition\n"
        "output from unit.math.addition\n"
    )
    assert "".join(output["test:unit.math.subtraction"]) == (
        "$ ctest unit.math.subtraction\n"
        "output from unit.math.subtraction\n"
    )


def test_run_all_uses_visible_filtered_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    app = LazytestApp(AppConfig())
    app.session = Session.from_tests(
        [
            DiscoveredTest("unit.math.addition"),
            DiscoveredTest("unit.db.insert"),
        ]
    )
    app.visible_tests = [app.session.tests_by_name["unit.db.insert"]]
    requested_names: list[str] = []

    monkeypatch.setattr(app, "run_tests_by_name", requested_names.extend)

    app.action_run_all()

    assert requested_names == ["unit.db.insert"]


@pytest.mark.asyncio
async def test_run_tests_by_name_builds_all_required_targets_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = LazytestApp(AppConfig())
    app.session = Session.from_tests(
        [
            DiscoveredTest("unit.math.addition", command=("/tmp/build/unit_tests",)),
            DiscoveredTest("integration.api.health", command=("/tmp/build/integration_tests",)),
        ]
    )
    events: list[str] = []

    async def fake_refresh_test_statuses(names: list[str]) -> None:
        return None

    async def fake_build_targets(config, targets, on_output):
        events.append(f"build:{','.join(targets)}")
        return ProcessResult(command=("cmake",), returncode=0)

    async def fake_run_test(config, test, on_output):
        events.append(f"test:{test.name}")
        return ProcessResult(command=("ctest",), returncode=0)

    async def fake_refresh_test_status(name: str) -> None:
        return None

    async def fake_append_output(text: str, *, key: str = "session") -> None:
        return None

    monkeypatch.setattr(app, "refresh_test_statuses", fake_refresh_test_statuses)
    monkeypatch.setattr(app, "refresh_test_status", fake_refresh_test_status)
    monkeypatch.setattr(app, "show_output", lambda key: None)
    monkeypatch.setattr(app, "append_output", fake_append_output)
    monkeypatch.setattr("lazytest.app.build_targets", fake_build_targets)
    monkeypatch.setattr("lazytest.app.run_test", fake_run_test)

    await app._run_tests_by_name(["unit.math.addition", "integration.api.health"])

    assert events == [
        "build:unit_tests,integration_tests",
        "test:unit.math.addition",
        "test:integration.api.health",
    ]


@pytest.mark.asyncio
async def test_refresh_test_status_updates_tree_labels_without_rebuilding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_discover(self: LazytestApp) -> None:
        return None

    monkeypatch.setattr(LazytestApp, "discover", fake_discover)
    app = LazytestApp(AppConfig())
    app.session = Session.from_tests(
        [
            DiscoveredTest("unit.math.addition", command=("/tmp/build/unit_tests",)),
            DiscoveredTest("unit.math.subtraction", command=("/tmp/build/unit_tests",)),
        ]
    )

    async with app.run_test():
        await app.apply_filter("", None)
        tree = app.query_one("#tests", Tree)
        clear_calls = 0
        original_clear = tree.clear

        def track_clear() -> None:
            nonlocal clear_calls
            clear_calls += 1
            original_clear()

        monkeypatch.setattr(tree, "clear", track_clear)

        app.session.set_status("unit.math.addition", Status.RUNNING)
        await app.refresh_test_status("unit.math.addition")

        assert clear_calls == 0
        assert app.test_nodes["unit.math.addition"].label.plain == "⟳ unit.math.addition"
        assert app.group_nodes["unit_tests"].label.plain == "⟳ unit_tests (2)"
