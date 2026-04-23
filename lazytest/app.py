from __future__ import annotations

import asyncio
import shlex
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from rich.markup import escape
from rich.style import Style
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.geometry import Offset, Region
from textual.selection import Selection
from textual.strip import Strip
from textual.widgets import Footer, Header, Input, RichLog, Static, Tree
from textual.widgets.tree import TreeNode

from lazytest.cmake_build import build_targets
from lazytest.cmake_file_api import ExecutableArtifactIndex, load_executable_artifacts
from lazytest.config import AppConfig, load_config
from lazytest.ctest_discovery import discovery_command, parse_ctest_json
from lazytest.models import DiscoveredTest, TestStatus
from lazytest.process_utils import collect_command
from lazytest.search import filter_tests, preserve_selection
from lazytest.session import TestSession
from lazytest.target_resolution import resolve_target
from lazytest.test_runner import run_test
from lazytest.theme import system_theme


@dataclass(frozen=True)
class StatusDisplay:
    marker: str
    style: str


@dataclass(frozen=True)
class TestNodeData:
    executable: str
    test_name: str | None = None
    output_key: str = "session"


STATUS_DISPLAYS = {
    TestStatus.UNKNOWN: StatusDisplay("○", "dim"),
    TestStatus.RUNNING: StatusDisplay("⟳", "yellow"),
    TestStatus.CANCELLED: StatusDisplay("■", "yellow"),
    TestStatus.PASSED: StatusDisplay("✓", "green"),
    TestStatus.FAILED: StatusDisplay("✗", "red"),
}
UNKNOWN_EXECUTABLE = "(unknown executable)"


class OutputLog(RichLog):
    can_focus = False
    FOCUS_ON_CLICK = False
    SELECTION_STYLE = Style(reverse=True)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._selection_anchor: Offset | None = None

    def get_selection(self, selection: Selection) -> tuple[str, str]:
        text = "\n".join(line.text.rstrip() for line in self.lines)
        return selection.extract(text), "\n"

    def render_line(self, y: int) -> Strip:
        line = super().render_line(y)
        selection = self.screen.selections.get(self)
        if selection is None:
            return line
        line_index = y + self.scroll_offset.y
        start, end = selection.get_span(line_index) or (0, 0)
        if start == end:
            return line
        if end == -1:
            end = len(self.lines[line_index].text.rstrip())
        start -= self.scroll_offset.x
        end -= self.scroll_offset.x
        return Strip.join(
            [
                line.crop(0, start),
                line.crop(start, end).apply_style(self.SELECTION_STYLE),
                line.crop(end),
            ]
        )

    def on_mouse_down(self, event: events.MouseDown) -> None:
        offset = self._event_to_text_offset(event)
        if offset is None:
            return
        event.stop()
        self.capture_mouse()
        self._selection_anchor = offset
        self.screen.selections = {self: Selection(offset, offset)}

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._selection_anchor is None:
            return
        offset = self._event_to_text_offset(event)
        if offset is None:
            return
        event.stop()
        self.screen.selections = {
            self: Selection.from_offsets(self._selection_anchor, offset)
        }

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._selection_anchor is None:
            return
        event.stop()
        offset = self._event_to_text_offset(event)
        if offset is not None:
            self.screen.selections = {
                self: Selection.from_offsets(self._selection_anchor, offset)
            }
        selected_text = self.screen.get_selected_text()
        self.release_mouse()
        self._selection_anchor = None
        self.screen.clear_selection()
        if selected_text:
            self.app.copy_to_clipboard(selected_text)
            self.app.notify("Selection copied to clipboard.")

    def _event_to_text_offset(self, event: events.MouseEvent) -> Offset | None:
        if not self.lines:
            return None
        x = int(event.screen_x) - self.scrollable_content_region.x + self.scroll_offset.x
        y = int(event.screen_y) - self.scrollable_content_region.y + self.scroll_offset.y
        y = max(0, min(y, len(self.lines) - 1))
        line_width = len(self.lines[y].text.rstrip())
        x = max(0, min(x, line_width))
        return Offset(x, y)


class SearchInput(Input):
    def on_key(self, event: events.Key) -> None:
        if event.key in {"down", "escape"}:
            event.stop()
            self.screen.query_one("#tests", Tree).focus()
        elif event.key == "ctrl+u":
            event.stop()
            self.app.action_page_up()
        elif event.key == "ctrl+d":
            event.stop()
            self.app.action_page_down()


class TestTree(Tree[TestNodeData]):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.auto_expand = False
        self._selected_expandable_node_id: int | None = None

    def action_cursor_up(self) -> None:
        if self.cursor_line <= self.first_test_line():
            self.screen.query_one("#search", Input).focus()
            return
        super().action_cursor_up()

    def on_key(self, event: events.Key) -> None:
        if event.key == "j":
            event.stop()
            self.action_cursor_down()
        elif event.key == "k":
            event.stop()
            self.action_cursor_up()

    def action_select_cursor(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.allow_expand and self._selected_expandable_node_id == id(node):
            self._toggle_node(node)
            return
        self._selected_expandable_node_id = id(node) if node.allow_expand else None
        self.post_message(Tree.NodeSelected(node))

    def watch_cursor_line(self, previous_line: int, line: int) -> None:
        super().watch_cursor_line(previous_line, line)
        if previous_line != line:
            self._selected_expandable_node_id = None

    def action_page_up(self) -> None:
        self._move_cursor_by_page(-1)

    def action_page_down(self) -> None:
        self._move_cursor_by_page(1)

    def first_test_line(self) -> int:
        if self.last_line < 0:
            return 0
        for line in range(max(0, self.last_line) + 1):
            node = self.get_node_at_line(line)
            data = node.data if node is not None else None
            if isinstance(data, TestNodeData) and data.test_name is not None:
                return line
        return 0

    def _move_cursor_by_page(self, direction: int) -> None:
        if self.last_line < 0:
            return
        page_size = max(1, self.scrollable_content_region.height - 1)
        target_line = max(0, min(self.cursor_line + (direction * page_size), self.last_line))
        node = self.get_node_at_line(target_line)
        if node is not None:
            self.move_cursor(node)
            self._center_cursor_line()

    def _center_cursor_line(self) -> None:
        self.scroll_to_region(
            Region(0, self.cursor_line, 1, 1),
            animate=False,
            center=True,
            force=True,
            immediate=True,
            x_axis=False,
        )


class LazytestApp(App[None]):
    TITLE = "lazytest"

    CSS = """
    Screen {
        layout: vertical;
    }

    #search {
        dock: top;
        height: 3;
    }

    #summary {
        height: 1;
        padding-left: 1;
    }

    #main {
        height: 1fr;
    }

    #left {
        height: 42%;
        border: solid $accent;
    }

    #output {
        height: 58%;
        border: solid $accent;
    }
    """

    BINDINGS = [
        Binding("enter", "run_selected", "Run", key_display="Enter", priority=True),
        Binding("x", "run_selected", "Run"),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("/", "focus_search", "Search"),
        Binding("ctrl+u", "page_up", "Page up"),
        Binding("ctrl+d", "page_down", "Page down"),
        Binding("f", "run_failed", "Run failed"),
        Binding("a", "run_all", "Run filtered"),
        Binding("ctrl+l", "clear_output", "Clear output"),
        Binding("c", "copy_output", "Copy output"),
        Binding("ctrl+c", "abort_run", "Abort"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, config: AppConfig | None = None) -> None:
        super().__init__()
        self.sync_system_theme()
        self.config = config or load_config(Path.cwd())
        self.executable_artifacts = ExecutableArtifactIndex()
        self.executable_identities: dict[str, str] = {}
        self.executable_basename_counts: dict[str, int] = {}
        self.session = TestSession()
        self.visible_tests: list[DiscoveredTest] = []
        self.output_buffers: dict[str, list[str]] = {"session": []}
        self.output_titles: dict[str, str] = {"session": "Output"}
        self.active_output_key = "session"
        self.test_nodes: dict[str, TreeNode[TestNodeData]] = {}
        self.group_nodes: dict[str, TreeNode[TestNodeData]] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield SearchInput(
            placeholder="Search tests by name, label, command, or working directory; use @label and !@label for tags",
            id="search",
        )
        yield Static("Discovering tests...", id="summary")
        with Vertical(id="main"):
            with Vertical(id="left"):
                tree: Tree[TestNodeData] = TestTree("Tests", id="tests")
                tree.show_root = False
                yield tree
            yield OutputLog(id="output", wrap=True, highlight=True)
        yield Footer()

    async def on_mount(self) -> None:
        self.set_interval(2, self.sync_system_theme)
        self.run_worker(self.discover(), exclusive=True)

    def sync_system_theme(self) -> None:
        theme = system_theme()
        if self.theme != theme:
            self.theme = theme

    @on(Input.Changed, "#search")
    async def on_search_changed(self, event: Input.Changed) -> None:
        selected = self.selected_test_name()
        await self.apply_filter(event.value, selected)

    @on(Input.Submitted, "#search")
    def on_search_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.focus_tests()

    @on(Tree.NodeHighlighted, "#tests")
    def on_test_highlighted(self, event: Tree.NodeHighlighted) -> None:
        data = event.node.data
        if isinstance(data, TestNodeData):
            self.show_output(data.output_key)

    @on(events.TextSelected)
    def on_text_selected(self, event: events.TextSelected) -> None:
        output = self.query_one("#output", OutputLog)
        selection = self.screen.selections.get(output)
        if selection is None:
            return
        selected_text = output.get_selection(selection)
        if selected_text is None:
            return
        text = "".join(selected_text).rstrip("\n")
        if not text:
            return
        self.copy_to_clipboard(text)
        self.screen.clear_selection()

    async def discover(self) -> None:
        await self.append_output(f"$ {' '.join(discovery_command(self.config))}")
        result = await collect_command(discovery_command(self.config))
        if not result.ok:
            await self.append_output(result.output)
            await self.append_output(f"CTest discovery failed with exit code {result.returncode}")
            return
        try:
            tests = parse_ctest_json(result.output)
        except ValueError as exc:
            await self.append_output(str(exc))
            return

        self.executable_artifacts = load_executable_artifacts(self.config.build_dir, tests)
        self.cache_executable_identities(tests)
        self.session = TestSession.from_tests(tests)
        await self.apply_filter(self.query_one("#search", Input).value, None)

    async def apply_filter(self, query: str, selected_name: str | None) -> None:
        self.visible_tests = filter_tests(self.session.tests, query)
        tree = self.query_one("#tests", Tree)
        tree.clear()
        self.test_nodes.clear()
        self.group_nodes.clear()
        if not self.visible_tests:
            tree.root.add_leaf("No matches")
        else:
            selected_node = None
            fallback_node = None
            groups = self.group_tests_by_executable(self.visible_tests)
            for executable, tests in groups.items():
                group_node = tree.root.add(
                    self.format_executable_group(executable, tests),
                    data=TestNodeData(executable, output_key=self.executable_output_key(executable)),
                    expand=True,
                )
                self.group_nodes[executable] = group_node
                for test in tests:
                    node = group_node.add_leaf(
                        self.format_test(test),
                        data=TestNodeData(
                            executable,
                            test.name,
                            self.test_output_key(test.name),
                        ),
                    )
                    self.test_nodes[test.name] = node
                    if fallback_node is None:
                        fallback_node = node
                    if test.name == selected_name:
                        selected_node = node
            index = preserve_selection(selected_name, self.visible_tests)
            if index is not None:
                tree.move_cursor(selected_node or fallback_node)
        summary = self.query_one("#summary", Static)
        summary.update(f"{len(self.visible_tests)} visible / {len(self.session.tests)} total")

    def group_tests_by_executable(
        self, tests: list[DiscoveredTest]
    ) -> dict[str, list[DiscoveredTest]]:
        groups: dict[str, list[DiscoveredTest]] = {}
        for test in tests:
            groups.setdefault(self.executable_identity(test), []).append(test)
        self.executable_basename_counts = Counter(
            Path(executable).name
            for executable in groups
            if executable != UNKNOWN_EXECUTABLE
        )
        return groups

    def executable_identity(self, test: DiscoveredTest) -> str:
        cached = self.executable_identities.get(test.name)
        if cached is not None:
            return cached
        return self.compute_executable_identity(test)

    def compute_executable_identity(self, test: DiscoveredTest) -> str:
        artifact = self.executable_artifacts.match_test_command(test, self.config.build_dir)
        if artifact is not None:
            return str(artifact.path)
        if test.command and test.command[0]:
            return test.command[0]
        return UNKNOWN_EXECUTABLE

    def cache_executable_identities(self, tests: list[DiscoveredTest]) -> None:
        self.executable_identities = {
            test.name: self.compute_executable_identity(test) for test in tests
        }

    def executable_label(self, test: DiscoveredTest) -> str:
        return self.executable_display(self.executable_identity(test))

    def executable_display(self, executable: str) -> str:
        if executable == UNKNOWN_EXECUTABLE:
            return executable
        label = Path(executable).name
        if self.executable_basename_counts.get(label, 0) > 1:
            return executable
        return label

    def executable_output_key(self, executable: str) -> str:
        return f"executable:{executable}"

    def test_output_key(self, test_name: str) -> str:
        return f"test:{test_name}"

    def format_executable_group(self, executable: str, tests: list[DiscoveredTest]) -> str:
        status = self.group_status(tests)
        display = STATUS_DISPLAYS[status]
        label = self.executable_display(executable)
        return f"[{display.style}]{display.marker} {escape(label)} ({len(tests)})[/]"

    def group_status(self, tests: list[DiscoveredTest]) -> TestStatus:
        statuses = {test.status for test in tests}
        if TestStatus.RUNNING in statuses:
            return TestStatus.RUNNING
        if TestStatus.FAILED in statuses:
            return TestStatus.FAILED
        if TestStatus.CANCELLED in statuses:
            return TestStatus.CANCELLED
        if statuses == {TestStatus.PASSED}:
            return TestStatus.PASSED
        return TestStatus.UNKNOWN

    def format_test(self, test: DiscoveredTest) -> str:
        display = STATUS_DISPLAYS[test.status]
        label_text = f"[{', '.join(test.labels)}]" if test.labels else ""
        labels = f" {escape(label_text)}" if label_text else ""
        return f"[{display.style}]{display.marker} {escape(test.name)}{labels}[/]"

    def selected_test_name(self) -> str | None:
        names = self.selected_test_names()
        return names[0] if len(names) == 1 else None

    def selected_test_names(self) -> list[str]:
        tree = self.query_one("#tests", Tree)
        data = tree.cursor_node.data
        if not isinstance(data, TestNodeData):
            return []
        if data.test_name is not None:
            return [data.test_name]
        return [
            test.name
            for test in self.visible_tests
            if self.executable_identity(test) == data.executable
        ]

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def focus_tests(self) -> None:
        self.query_one("#tests", Tree).focus()

    def action_page_up(self) -> None:
        tree = self.query_one("#tests", TestTree)
        if self.focused is not tree:
            tree.focus()
        tree.action_page_up()

    def action_page_down(self) -> None:
        tree = self.query_one("#tests", TestTree)
        if self.focused is not tree:
            tree.focus()
        tree.action_page_down()

    def action_clear_output(self) -> None:
        self.clear_output(self.active_output_key)

    def action_copy_output(self) -> None:
        text = self.active_output_text()
        if not text:
            self.notify("No output to copy.", severity="warning")
            return
        self.copy_to_clipboard(text)
        self.notify("Output copied to clipboard.")

    def action_abort_run(self) -> None:
        cancelled = self.workers.cancel_group(self, "run")
        if cancelled:
            self.notify("Aborting current build/tests.", severity="warning")
            return
        self.notify("No active build or test run.", severity="warning")

    def action_refresh(self) -> None:
        self.run_worker(self.discover(), exclusive=True)

    def action_run_selected(self) -> None:
        if self.focused is self.query_one("#search", Input):
            self.focus_tests()
            return
        names = self.selected_test_names()
        if names:
            self.run_tests_by_name(names)

    def action_run_failed(self) -> None:
        self.run_tests_by_name([test.name for test in self.session.failed_tests()])

    def action_run_all(self) -> None:
        self.run_tests_by_name([test.name for test in self.visible_tests])

    @work(exclusive=True, group="run")
    async def run_tests_by_name(self, names: list[str]) -> None:
        await self._run_tests_by_name(names)

    async def _run_tests_by_name(self, names: list[str]) -> None:
        tests = self.tests_for_names(names)
        if not tests:
            await self.append_output("No tests selected.")
            return

        tests_by_target: dict[str, tuple[str, list[DiscoveredTest]]] = {}
        for test in tests:
            self.clear_output(self.test_output_key(test.name))
            resolution = resolve_target(test, self.config, self.executable_artifacts)
            if not resolution.target:
                await self.append_output(
                    f"{resolution.reason}\n",
                    key=self.test_output_key(test.name),
                )
                self.session.set_status(test.name, TestStatus.FAILED)
                await self.refresh_test_status(test.name)
                continue
            reason, target_tests = tests_by_target.setdefault(
                resolution.target,
                (resolution.reason, []),
            )
            target_tests.append(test)

        if not tests_by_target:
            return

        targets = list(tests_by_target)
        all_target_tests = [
            test
            for _, target_tests in tests_by_target.values()
            for test in target_tests
        ]
        group_keys = list(
            dict.fromkeys(
                self.executable_output_key(self.executable_identity(test))
                for test in all_target_tests
            )
        )
        for group_key in group_keys:
            self.clear_output(group_key)
        if group_keys:
            self.show_output(group_keys[0])

        async def append_build_output(text: str) -> None:
            await self.append_output(text)
            for group_key in group_keys:
                await self.append_output(text, key=group_key)

        async def append_build_process_id(pid: int) -> None:
            self.set_output_process_id(pid)
            for group_key in group_keys:
                self.set_output_process_id(pid, key=group_key)
            await append_build_output(f"process id: {pid}\n")

        for test in all_target_tests:
            self.session.set_status(test.name, TestStatus.RUNNING)
        await self.refresh_test_statuses([test.name for test in all_target_tests])

        if len(targets) == 1:
            reason = tests_by_target[targets[0]][0]
            await append_build_output(f"$ cmake --build target {targets[0]} ({reason})\n")
        else:
            await append_build_output(f"$ cmake --build targets {', '.join(targets)}\n")
        try:
            build_result = await build_targets(
                self.config,
                targets,
                append_build_output,
                on_start=append_build_process_id,
            )
            if not build_result.ok:
                for test in all_target_tests:
                    self.session.set_status(test.name, TestStatus.FAILED)
                await self.refresh_test_statuses([test.name for test in all_target_tests])
                return

            for _, target_tests in tests_by_target.values():
                for test in target_tests:
                    test_key = self.test_output_key(test.name)
                    self.show_output(test_key)
                    await self.append_output(f"$ {self.test_run_label(test)}\n", key=test_key)
                    test_result = await run_test(
                        self.config,
                        test,
                        lambda text, key=test_key: self.append_output(text, key=key),
                        on_start=lambda pid, key=test_key: self.append_process_id(
                            pid,
                            key=key,
                        ),
                    )
                    self.session.set_status(
                        test.name,
                        TestStatus.PASSED if test_result.ok else TestStatus.FAILED,
                    )
                    await self.refresh_test_status(test.name)
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            cancelled_names = [
                test.name
                for test in all_target_tests
                if self.session.tests_by_name[test.name].status is TestStatus.RUNNING
            ]
            for name in cancelled_names:
                self.session.set_status(name, TestStatus.CANCELLED)
            await self.refresh_test_statuses(cancelled_names)
            await self.append_output("Run aborted.\n")
            raise

    def tests_for_names(self, names: list[str]) -> list[DiscoveredTest]:
        tests: list[DiscoveredTest] = []
        seen: set[str] = set()
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            test = self.session.tests_by_name.get(name)
            if test is not None:
                tests.append(test)
        return tests

    def test_run_label(self, test: DiscoveredTest) -> str:
        if test.command:
            return shlex.join(test.command)
        return f"ctest {test.name}"

    async def append_process_id(self, pid: int, *, key: str = "session") -> None:
        self.set_output_process_id(pid, key=key)
        await self.append_output(f"process id: {pid}\n", key=key)

    def set_output_process_id(self, pid: int, *, key: str = "session") -> None:
        self.output_titles[key] = f"pid {pid}"
        if key == self.active_output_key and self.is_running:
            self.update_output_title()

    async def refresh_test_status(self, name: str) -> None:
        await self.refresh_test_statuses([name])

    async def refresh_test_statuses(self, names: list[str]) -> None:
        updated_groups: set[str] = set()
        for name in names:
            test = self.session.tests_by_name.get(name)
            node = self.test_nodes.get(name)
            if test is None or node is None:
                continue
            node.set_label(self.format_test(test))
            updated_groups.add(self.executable_identity(test))

        for executable in updated_groups:
            node = self.group_nodes.get(executable)
            if node is None:
                continue
            tests = [
                self.session.tests_by_name[test.name]
                for test in self.visible_tests
                if self.executable_identity(test) == executable
            ]
            node.set_label(self.format_executable_group(executable, tests))

    def clear_output(self, key: str) -> None:
        self.output_buffers[key] = []
        self.output_titles[key] = "Output"
        if key == self.active_output_key:
            self.render_output()

    def show_output(self, key: str) -> None:
        self.output_buffers.setdefault(key, [])
        self.output_titles.setdefault(key, "Output")
        self.active_output_key = key
        self.render_output()

    def render_output(self) -> None:
        output = self.query_one("#output", OutputLog)
        output.clear()
        self.update_output_title()
        for text in self.output_buffers.get(self.active_output_key, []):
            output.write(text.rstrip("\n"))

    def update_output_title(self) -> None:
        output = self.query_one("#output", OutputLog)
        output.border_title = self.output_titles.get(self.active_output_key, "Output")

    def active_output_text(self) -> str:
        return "".join(self.output_buffers.get(self.active_output_key, []))

    async def append_output(self, text: str, *, key: str = "session") -> None:
        self.output_buffers.setdefault(key, []).append(text)
        if key == self.active_output_key:
            output = self.query_one("#output", OutputLog)
            output.write(text.rstrip("\n"), scroll_end=output.is_vertical_scroll_end)


def run() -> None:
    LazytestApp().run()
