import asyncio
from pathlib import Path

import pytest
from rich.text import Text
from textual import events
from textual.geometry import Offset
from textual.selection import Selection
from textual.widgets import Input, Static, Tree

from lazytest.app import LazytestApp, OutputLog
from lazytest.cmake_file_api import ExecutableArtifact, ExecutableArtifactIndex
from lazytest.config import AppConfig
from lazytest.models import DiscoveredTest, ProcessResult, TestStatus as Status
from lazytest.session import TestSession as Session


def test_x_binding_is_removed() -> None:
    assert all(binding.key != "x" for binding in LazytestApp.BINDINGS)


def test_format_test_uses_colored_status_markers() -> None:
    app = LazytestApp(AppConfig())

    assert app.format_test(DiscoveredTest("not.run")) == "[dim]○ not.run[/]"
    assert app.format_test(DiscoveredTest("active", status=Status.RUNNING)) == "[yellow]⟳ active[/]"
    assert app.format_test(DiscoveredTest("stopped", status=Status.CANCELLED)) == "[yellow]■ stopped[/]"
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

    assert list(groups) == ["/tmp/build/unit_tests", "/tmp/build/integration_tests"]
    assert [test.name for test in groups["/tmp/build/unit_tests"]] == ["a", "b"]
    assert app.executable_label(tests[0]) == "unit_tests"


def test_group_tests_by_executable_keeps_same_basenames_separate() -> None:
    app = LazytestApp(AppConfig())
    tests = [
        DiscoveredTest("a", command=("/tmp/debug/check", "a")),
        DiscoveredTest("b", command=("/tmp/release/check", "b")),
    ]
    app.visible_tests = tests

    groups = app.group_tests_by_executable(tests)

    assert list(groups) == ["/tmp/debug/check", "/tmp/release/check"]
    assert [test.name for test in groups["/tmp/debug/check"]] == ["a"]
    assert [test.name for test in groups["/tmp/release/check"]] == ["b"]
    assert app.executable_display("/tmp/debug/check") == "/tmp/debug/check"


def test_group_tests_by_executable_uses_file_api_artifact_for_wrapper() -> None:
    build_dir = Path("/tmp/build")
    app = LazytestApp(AppConfig(build_dir=build_dir))
    app.executable_artifacts = ExecutableArtifactIndex(
        (
            ExecutableArtifact(
                path=build_dir / "test-wrapper-case",
                target="test-wrapper-case",
                file_name="test-wrapper-case",
            ),
        )
    )
    tests = [
        DiscoveredTest(
            "wrapper",
            command=("bash", "-c", "make test-wrapper-case && /tmp/build/test-wrapper-case"),
            working_directory=build_dir,
        ),
    ]
    app.visible_tests = tests

    groups = app.group_tests_by_executable(tests)

    assert list(groups) == ["/tmp/build/test-wrapper-case"]
    assert app.executable_label(tests[0]) == "test-wrapper-case"


def test_group_tests_by_executable_uses_wrapped_absolute_binary_without_file_api() -> None:
    app = LazytestApp(AppConfig(build_dir=Path("/tmp/build")))
    tests = [
        DiscoveredTest(
            "legacy.random.check1",
            command=(
                "/opt/homebrew/bin/mpiexec",
                "-n",
                "4",
                "/tmp/build/openqcd_devel_random_check1",
            ),
            working_directory=Path("/tmp/build/test_runs/legacy.random.check1"),
        ),
    ]
    app.visible_tests = tests

    groups = app.group_tests_by_executable(tests)

    assert list(groups) == ["/tmp/build/openqcd_devel_random_check1"]
    assert app.executable_label(tests[0]) == "openqcd_devel_random_check1"


def test_group_formatting_reuses_cached_executable_identities() -> None:
    class CountingArtifacts:
        def __init__(self) -> None:
            self.calls = 0

        def match_test_command(self, test: DiscoveredTest, build_dir: Path):
            self.calls += 1
            return None

    artifacts = CountingArtifacts()
    app = LazytestApp(AppConfig(build_dir=Path("/tmp/build")))
    app.executable_artifacts = artifacts
    tests = [
        DiscoveredTest(f"test.{index}", command=(f"/tmp/build/test_{index}",))
        for index in range(20)
    ]

    app.cache_executable_identities(tests)
    app.visible_tests = tests
    groups = app.group_tests_by_executable(tests)
    for executable, group_tests in groups.items():
        app.format_executable_group(executable, group_tests)

    assert artifacts.calls == len(tests)


def test_group_status_reports_cancelled_tests() -> None:
    app = LazytestApp(AppConfig())

    assert app.group_status([DiscoveredTest("stopped", status=Status.CANCELLED)]) is Status.CANCELLED


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

    async def fake_build_targets(config, targets, on_output, on_start=None):
        events.append(f"build:{','.join(targets)}")
        if on_start is not None:
            await on_start(1234)
        return ProcessResult(command=("cmake",), returncode=0)

    async def fake_run_test(config, test, on_output, on_start=None):
        events.append(f"test:{test.name}")
        if on_start is not None:
            await on_start(2000 + len(events))
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
    assert "".join(output["session"]) == (
        "$ cmake --build target unit_tests (using configured default_build_target)\n"
        "process id: 1234\n"
    )
    assert "".join(output["test:unit.math.addition"]) == (
        "$ ctest unit.math.addition\n"
        "process id: 2002\n"
        "output from unit.math.addition\n"
    )
    assert "".join(output["test:unit.math.subtraction"]) == (
        "$ ctest unit.math.subtraction\n"
        "process id: 2003\n"
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


def test_copy_output_uses_active_output_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    app = LazytestApp(AppConfig())
    app.active_output_key = "test:unit.math.addition"
    app.output_buffers["test:unit.math.addition"] = [
        "$ ctest unit.math.addition\n",
        "first line\nsecond line\n",
    ]
    copied: list[str] = []
    notifications: list[str] = []

    monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
    monkeypatch.setattr(app, "notify", lambda message, **kwargs: notifications.append(message))

    app.action_copy_output()

    assert copied == ["$ ctest unit.math.addition\nfirst line\nsecond line\n"]
    assert notifications == ["Output copied to clipboard."]


def test_copy_output_warns_when_active_output_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = LazytestApp(AppConfig())
    copied: list[str] = []
    notifications: list[tuple[str, str | None]] = []

    monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
    monkeypatch.setattr(
        app,
        "notify",
        lambda message, **kwargs: notifications.append(
            (message, kwargs.get("severity"))
        ),
    )

    app.action_copy_output()

    assert copied == []
    assert notifications == [("No output to copy.", "warning")]


def test_output_log_is_selectable_without_being_focusable() -> None:
    assert OutputLog.can_focus is False
    assert OutputLog.FOCUS_ON_CLICK is False
    assert OutputLog.ALLOW_SELECT is True


def test_app_uses_system_theme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lazytest.app.system_theme", lambda: "textual-light")

    app = LazytestApp(AppConfig())

    assert app.theme == "textual-light"


@pytest.mark.asyncio
async def test_startup_paints_before_discovery_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    finish = asyncio.Event()

    async def slow_discover(self: LazytestApp) -> None:
        started.set()
        await finish.wait()

    monkeypatch.setattr(LazytestApp, "discover", slow_discover)
    app = LazytestApp(AppConfig())

    async with app.run_test() as pilot:
        await started.wait()
        await pilot.pause()

        assert str(app.query_one("#summary", Static).render()) == "Discovering tests..."

        finish.set()
        await pilot.pause()


@pytest.mark.asyncio
async def test_output_title_shows_active_process_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_discover(self: LazytestApp) -> None:
        return None

    monkeypatch.setattr(LazytestApp, "discover", fake_discover)
    app = LazytestApp(AppConfig())

    async with app.run_test():
        output = app.query_one("#output", OutputLog)

        await app.append_process_id(4321)

        assert output.border_title == "pid 4321"

        app.action_clear_output()

        assert output.border_title == "Output"
        assert output.border_subtitle is None


@pytest.mark.asyncio
async def test_output_title_follows_visible_output_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_discover(self: LazytestApp) -> None:
        return None

    monkeypatch.setattr(LazytestApp, "discover", fake_discover)
    app = LazytestApp(AppConfig())

    async with app.run_test():
        output = app.query_one("#output", OutputLog)

        app.show_output("test:unit.math.addition")
        await app.append_process_id(2002, key="test:unit.math.addition")
        await app.append_process_id(2003, key="test:unit.math.subtraction")

        assert output.border_title == "pid 2002"

        app.show_output("test:unit.math.subtraction")

        assert output.border_title == "pid 2003"

        app.clear_output("test:unit.math.subtraction")

        assert output.border_title == "Output"


@pytest.mark.asyncio
async def test_output_subtitle_shows_ctrl_c_hint_while_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_discover(self: LazytestApp) -> None:
        return None

    monkeypatch.setattr(LazytestApp, "discover", fake_discover)
    app = LazytestApp(AppConfig())

    async with app.run_test():
        output = app.query_one("#output", OutputLog)

        assert output.border_subtitle is None

        app.show_abort_hint = True
        app.update_output_chrome()

        assert output.styles.border_subtitle_align == "left"
        assert output.border_subtitle == "Ctrl+C abort"

        app.show_abort_hint = False
        app.update_output_chrome()

        assert output.border_subtitle is None


@pytest.mark.asyncio
async def test_output_append_pauses_following_when_scrolled_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_discover(self: LazytestApp) -> None:
        return None

    monkeypatch.setattr(LazytestApp, "discover", fake_discover)
    app = LazytestApp(AppConfig())

    async with app.run_test(size=(80, 12)) as pilot:
        output = app.query_one("#output", OutputLog)
        for index in range(30):
            await app.append_output(f"line {index}\n")
        await pilot.pause()
        assert output.is_vertical_scroll_end

        output.scroll_home(animate=False)
        await pilot.pause()
        scrolled_up_y = output.scroll_y

        await app.append_output("new line\n")
        await pilot.pause()

        assert output.scroll_y == scrolled_up_y
        assert not output.is_vertical_scroll_end


@pytest.mark.asyncio
async def test_output_append_follows_when_already_at_bottom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_discover(self: LazytestApp) -> None:
        return None

    monkeypatch.setattr(LazytestApp, "discover", fake_discover)
    app = LazytestApp(AppConfig())

    async with app.run_test(size=(80, 12)) as pilot:
        output = app.query_one("#output", OutputLog)
        for index in range(30):
            await app.append_output(f"line {index}\n")
        await pilot.pause()
        assert output.is_vertical_scroll_end

        await app.append_output("new line\n")
        await pilot.pause()

        assert output.is_vertical_scroll_end


@pytest.mark.asyncio
async def test_output_selection_is_rendered_visibly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_discover(self: LazytestApp) -> None:
        return None

    monkeypatch.setattr(LazytestApp, "discover", fake_discover)
    app = LazytestApp(AppConfig())

    async with app.run_test(size=(100, 30)):
        output = app.query_one("#output", OutputLog)
        output.write("first line")
        app.screen.selections = {
            output: Selection(Offset(0, 0), Offset(5, 0)),
        }

        rendered = output.render_line(0)
        selected = rendered.crop(0, 5)
        unselected = rendered.crop(5, 10)

        assert selected.text == "first"
        assert "reverse" in str(selected._segments[0].style)
        assert "reverse" not in str(unselected._segments[0].style)


@pytest.mark.asyncio
async def test_output_multiline_selection_is_rendered_visibly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_discover(self: LazytestApp) -> None:
        return None

    monkeypatch.setattr(LazytestApp, "discover", fake_discover)
    app = LazytestApp(AppConfig())

    async with app.run_test(size=(100, 30)):
        output = app.query_one("#output", OutputLog)
        output.write("first line")
        output.write("middle line")
        output.write("last line")
        app.screen.selections = {
            output: Selection(Offset(2, 0), Offset(4, 2)),
        }

        first = output.render_line(0)
        middle = output.render_line(1)
        last = output.render_line(2)

        assert "reverse" not in str(first.crop(0, 2)._segments[0].style)
        assert "reverse" in str(first.crop(2, 10)._segments[0].style)
        assert "reverse" in str(middle.crop(0, 11)._segments[0].style)
        assert "reverse" in str(last.crop(0, 4)._segments[0].style)
        assert "reverse" not in str(last.crop(4, 9)._segments[0].style)


@pytest.mark.asyncio
async def test_output_selection_copies_text_and_clears_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_discover(self: LazytestApp) -> None:
        return None

    monkeypatch.setattr(LazytestApp, "discover", fake_discover)
    app = LazytestApp(AppConfig())
    copied: list[str] = []

    monkeypatch.setattr(app, "copy_to_clipboard", copied.append)

    async with app.run_test():
        output = app.query_one("#output", OutputLog)
        output.write("first line")
        output.write("second line")
        app.screen.selections = {
            output: Selection(Offset(0, 0), Offset(6, 1)),
        }

        app.on_text_selected(events.TextSelected())

        assert copied == ["first line\nsecond"]
        assert app.screen.selections == {}


@pytest.mark.asyncio
async def test_output_mouse_drag_copies_text_and_clears_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_discover(self: LazytestApp) -> None:
        return None

    monkeypatch.setattr(LazytestApp, "discover", fake_discover)
    app = LazytestApp(AppConfig())
    copied: list[str] = []
    notifications: list[str] = []

    monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
    monkeypatch.setattr(app, "notify", lambda message, **kwargs: notifications.append(message))

    async with app.run_test(size=(100, 30)) as pilot:
        output = app.query_one("#output", OutputLog)
        output.write("first line")
        await pilot.pause()

        await pilot.mouse_down(output, offset=(1, 1))
        await pilot.hover(output, offset=(6, 1))
        await pilot.mouse_up(output, offset=(6, 1))
        await pilot.pause()

        assert copied == ["first"]
        assert notifications == ["Selection copied to clipboard."]
        assert app.screen.selections == {}


@pytest.mark.asyncio
async def test_group_selects_before_toggling_expansion(
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
        group_node = app.group_nodes["/tmp/build/unit_tests"]
        tree.move_cursor(group_node)

        tree.action_select_cursor()
        assert group_node.is_expanded

        tree.action_select_cursor()
        assert not group_node.is_expanded

        tree.action_select_cursor()
        assert group_node.is_expanded


@pytest.mark.asyncio
async def test_arrow_up_from_first_test_focuses_search(
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

    async with app.run_test() as pilot:
        await app.apply_filter("", None)
        tree = app.query_one("#tests", Tree)
        tree.focus()
        await pilot.pause()

        await pilot.press("up")

        assert app.focused is app.query_one("#search", Input)


@pytest.mark.asyncio
async def test_vim_keys_move_test_cursor(
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

    async with app.run_test() as pilot:
        await app.apply_filter("", None)
        tree = app.query_one("#tests", Tree)
        tree.focus()
        await pilot.pause()

        await pilot.press("j")
        assert app.selected_test_name() == "unit.math.addition"

        await pilot.press("j")
        assert app.selected_test_name() == "unit.math.subtraction"

        await pilot.press("k")
        assert app.selected_test_name() == "unit.math.addition"


@pytest.mark.asyncio
async def test_k_from_first_test_focuses_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_discover(self: LazytestApp) -> None:
        return None

    monkeypatch.setattr(LazytestApp, "discover", fake_discover)
    app = LazytestApp(AppConfig())
    app.session = Session.from_tests([DiscoveredTest("unit.math.addition")])

    async with app.run_test() as pilot:
        await app.apply_filter("", None)
        tree = app.query_one("#tests", Tree)
        tree.focus()
        await pilot.pause()

        await pilot.press("k")

        assert app.focused is app.query_one("#search", Input)


@pytest.mark.asyncio
async def test_search_down_and_enter_focus_tests_without_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_discover(self: LazytestApp) -> None:
        return None

    monkeypatch.setattr(LazytestApp, "discover", fake_discover)
    app = LazytestApp(AppConfig())
    app.session = Session.from_tests([DiscoveredTest("unit.math.addition")])
    requested_names: list[str] = []

    monkeypatch.setattr(app, "run_tests_by_name", requested_names.extend)

    async with app.run_test() as pilot:
        await app.apply_filter("", None)
        search = app.query_one("#search", Input)
        tree = app.query_one("#tests", Tree)

        search.focus()
        await pilot.press("down")
        assert app.focused is tree

        search.focus()
        await pilot.press("enter")
        assert app.focused is tree
        assert requested_names == []


@pytest.mark.asyncio
async def test_search_escape_focuses_tests_without_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_discover(self: LazytestApp) -> None:
        return None

    monkeypatch.setattr(LazytestApp, "discover", fake_discover)
    app = LazytestApp(AppConfig())
    app.session = Session.from_tests([DiscoveredTest("unit.math.addition")])
    requested_names: list[str] = []

    monkeypatch.setattr(app, "run_tests_by_name", requested_names.extend)

    async with app.run_test() as pilot:
        await app.apply_filter("", None)
        search = app.query_one("#search", Input)
        tree = app.query_one("#tests", Tree)

        search.focus()
        await pilot.press("escape")

        assert app.focused is tree
        assert requested_names == []


@pytest.mark.asyncio
async def test_ctrl_u_and_ctrl_d_page_the_test_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_discover(self: LazytestApp) -> None:
        return None

    monkeypatch.setattr(LazytestApp, "discover", fake_discover)
    app = LazytestApp(AppConfig())
    app.session = Session.from_tests(
        [
            DiscoveredTest(f"unit.test_{index}", command=("/tmp/build/unit_tests",))
            for index in range(40)
        ]
    )
    centered_regions: list[tuple[int, bool]] = []

    async with app.run_test(size=(80, 12)) as pilot:
        await app.apply_filter("", None)
        search = app.query_one("#search", Input)
        tree = app.query_one("#tests", Tree)
        tree.move_cursor(app.test_nodes["unit.test_0"])

        original_scroll_to_region = tree.scroll_to_region

        def record_scroll_to_region(region, **kwargs):
            centered_regions.append((region.y, kwargs.get("center", False)))
            return original_scroll_to_region(region, **kwargs)

        monkeypatch.setattr(tree, "scroll_to_region", record_scroll_to_region)

        search.focus()
        await pilot.pause()
        start_selection = app.selected_test_name()

        await pilot.press("ctrl+d")
        await pilot.pause()
        after_page_down_selection = app.selected_test_name()

        await pilot.press("ctrl+u")
        await pilot.pause()

        assert app.focused is tree
        assert start_selection == "unit.test_0"
        assert after_page_down_selection != start_selection
        assert any(centered for _, centered in centered_regions)
        assert app.selected_test_name() == start_selection


@pytest.mark.asyncio
async def test_run_tests_by_name_builds_all_required_targets_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_dir = Path("/tmp/build")
    app = LazytestApp(AppConfig(build_dir=build_dir))
    app.executable_artifacts = ExecutableArtifactIndex(
        (
            ExecutableArtifact(
                path=build_dir / "unit_tests",
                target="unit_tests",
                file_name="unit_tests",
            ),
            ExecutableArtifact(
                path=build_dir / "integration_tests",
                target="integration_tests",
                file_name="integration_tests",
            ),
        )
    )
    app.session = Session.from_tests(
        [
            DiscoveredTest("unit.math.addition", command=("/tmp/build/unit_tests",)),
            DiscoveredTest("integration.api.health", command=("/tmp/build/integration_tests",)),
        ]
    )
    events: list[str] = []

    async def fake_refresh_test_statuses(names: list[str]) -> None:
        return None

    async def fake_build_targets(config, targets, on_output, on_start=None):
        events.append(f"build:{','.join(targets)}")
        return ProcessResult(command=("cmake",), returncode=0)

    async def fake_run_test(config, test, on_output, on_start=None):
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
async def test_cancelling_run_marks_running_tests_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = LazytestApp(AppConfig(default_build_target="unit_tests"))
    app.session = Session.from_tests(
        [
            DiscoveredTest("unit.math.addition"),
            DiscoveredTest("unit.math.subtraction"),
        ]
    )
    build_started = asyncio.Event()
    output: list[str] = []

    async def fake_refresh_test_statuses(names: list[str]) -> None:
        return None

    async def fake_build_targets(config, targets, on_output, on_start=None):
        build_started.set()
        await asyncio.Future()

    async def fake_append_output(text: str, *, key: str = "session") -> None:
        output.append(text)

    monkeypatch.setattr(app, "refresh_test_statuses", fake_refresh_test_statuses)
    monkeypatch.setattr(app, "show_output", lambda key: None)
    monkeypatch.setattr(app, "append_output", fake_append_output)
    monkeypatch.setattr("lazytest.app.build_targets", fake_build_targets)

    task = asyncio.create_task(
        app._run_tests_by_name(["unit.math.addition", "unit.math.subtraction"])
    )
    await build_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert app.session.tests_by_name["unit.math.addition"].status is Status.CANCELLED
    assert app.session.tests_by_name["unit.math.subtraction"].status is Status.CANCELLED
    assert output[-1] == "Run aborted.\n"


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
        assert app.group_nodes["/tmp/build/unit_tests"].label.plain == "⟳ unit_tests (2)"
