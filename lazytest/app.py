from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from rich.markup import escape
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static, Tree

from lazytest.cmake_build import build_target
from lazytest.config import AppConfig, load_config
from lazytest.ctest_discovery import discovery_command, parse_ctest_json
from lazytest.models import DiscoveredTest, TestStatus
from lazytest.process_utils import collect_command
from lazytest.search import filter_tests, preserve_selection
from lazytest.session import TestSession
from lazytest.target_resolution import resolve_target
from lazytest.test_runner import run_test


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
    TestStatus.PASSED: StatusDisplay("✓", "green"),
    TestStatus.FAILED: StatusDisplay("✗", "red"),
}


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
        width: 42%;
        border: solid $accent;
    }

    #output {
        width: 58%;
        border: solid $accent;
    }
    """

    BINDINGS = [
        Binding("enter", "run_selected", "Run", key_display="Enter", priority=True),
        Binding("x", "run_selected", "Run"),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("/", "focus_search", "Search"),
        Binding("ctrl+u", "clear_search", "Clear search"),
        Binding("f", "run_failed", "Run failed"),
        Binding("a", "run_all", "Run all"),
        Binding("ctrl+l", "clear_output", "Clear output"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, config: AppConfig | None = None) -> None:
        super().__init__()
        self.config = config or load_config(Path.cwd())
        self.session = TestSession()
        self.visible_tests: list[DiscoveredTest] = []
        self.output_buffers: dict[str, list[str]] = {"session": []}
        self.active_output_key = "session"

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search tests by name, label, command, or working directory", id="search")
        yield Static("Discovering tests...", id="summary")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                tree: Tree[TestNodeData] = Tree("Tests", id="tests")
                tree.show_root = False
                yield tree
            yield RichLog(id="output", wrap=True, highlight=True)
        yield Footer()

    async def on_mount(self) -> None:
        await self.discover()

    @on(Input.Changed, "#search")
    async def on_search_changed(self, event: Input.Changed) -> None:
        selected = self.selected_test_name()
        await self.apply_filter(event.value, selected)

    @on(Input.Submitted, "#search")
    def on_search_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_run_selected()

    @on(Tree.NodeHighlighted, "#tests")
    def on_test_highlighted(self, event: Tree.NodeHighlighted) -> None:
        data = event.node.data
        if isinstance(data, TestNodeData):
            self.show_output(data.output_key)

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
        self.session = TestSession.from_tests(tests)
        await self.apply_filter(self.query_one("#search", Input).value, None)

    async def apply_filter(self, query: str, selected_name: str | None) -> None:
        self.visible_tests = filter_tests(self.session.tests, query)
        tree = self.query_one("#tests", Tree)
        tree.clear()
        if not self.visible_tests:
            tree.root.add_leaf("No matches")
        else:
            selected_node = None
            fallback_node = None
            for executable, tests in self.group_tests_by_executable(self.visible_tests).items():
                group_node = tree.root.add(
                    self.format_executable_group(executable, tests),
                    data=TestNodeData(executable, output_key=self.executable_output_key(executable)),
                    expand=True,
                )
                for test in tests:
                    node = group_node.add_leaf(
                        self.format_test(test),
                        data=TestNodeData(
                            executable,
                            test.name,
                            self.test_output_key(test.name),
                        ),
                    )
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
            groups.setdefault(self.executable_label(test), []).append(test)
        return groups

    def executable_label(self, test: DiscoveredTest) -> str:
        if test.command and test.command[0]:
            return Path(test.command[0]).name
        return "(unknown executable)"

    def executable_output_key(self, executable: str) -> str:
        return f"executable:{executable}"

    def test_output_key(self, test_name: str) -> str:
        return f"test:{test_name}"

    def format_executable_group(self, executable: str, tests: list[DiscoveredTest]) -> str:
        status = self.group_status(tests)
        display = STATUS_DISPLAYS[status]
        return f"[{display.style}]{display.marker} {escape(executable)} ({len(tests)})[/]"

    def group_status(self, tests: list[DiscoveredTest]) -> TestStatus:
        statuses = {test.status for test in tests}
        if TestStatus.RUNNING in statuses:
            return TestStatus.RUNNING
        if TestStatus.FAILED in statuses:
            return TestStatus.FAILED
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
            if self.executable_label(test) == data.executable
        ]

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_clear_search(self) -> None:
        self.query_one("#search", Input).value = ""

    def action_clear_output(self) -> None:
        self.output_buffers[self.active_output_key] = []
        self.render_output()

    def action_refresh(self) -> None:
        self.run_worker(self.discover(), exclusive=True)

    def action_run_selected(self) -> None:
        names = self.selected_test_names()
        if names:
            self.run_tests_by_name(names)

    def action_run_failed(self) -> None:
        self.run_tests_by_name([test.name for test in self.session.failed_tests()])

    def action_run_all(self) -> None:
        self.run_tests_by_name([test.name for test in self.session.tests])

    @work(exclusive=True)
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
            resolution = resolve_target(test, self.config)
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

        for target, (reason, target_tests) in tests_by_target.items():
            group_keys = list(
                dict.fromkeys(
                    self.executable_output_key(self.executable_label(test))
                    for test in target_tests
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

            for test in target_tests:
                self.session.set_status(test.name, TestStatus.RUNNING)
            await self.refresh_test_status(target_tests[0].name)
            await append_build_output(f"$ cmake --build target {target} ({reason})\n")
            build_result = await build_target(self.config, target, append_build_output)
            if not build_result.ok:
                for test in target_tests:
                    self.session.set_status(test.name, TestStatus.FAILED)
                await self.refresh_test_status(target_tests[0].name)
                continue

            for test in target_tests:
                test_key = self.test_output_key(test.name)
                self.show_output(test_key)
                await self.append_output(f"$ ctest {test.name}\n", key=test_key)
                test_result = await run_test(
                    self.config,
                    test,
                    lambda text, key=test_key: self.append_output(text, key=key),
                )
                self.session.set_status(
                    test.name,
                    TestStatus.PASSED if test_result.ok else TestStatus.FAILED,
                )
                await self.refresh_test_status(test.name)
                await asyncio.sleep(0)

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

    async def refresh_test_status(self, name: str) -> None:
        await self.apply_filter(self.query_one("#search", Input).value, name)

    def clear_output(self, key: str) -> None:
        self.output_buffers[key] = []
        if key == self.active_output_key:
            self.render_output()

    def show_output(self, key: str) -> None:
        self.output_buffers.setdefault(key, [])
        self.active_output_key = key
        self.render_output()

    def render_output(self) -> None:
        output = self.query_one("#output", RichLog)
        output.clear()
        for text in self.output_buffers.get(self.active_output_key, []):
            output.write(text.rstrip("\n"))

    async def append_output(self, text: str, *, key: str = "session") -> None:
        self.output_buffers.setdefault(key, []).append(text)
        if key == self.active_output_key:
            self.query_one("#output", RichLog).write(text.rstrip("\n"))


def run() -> None:
    LazytestApp().run()
