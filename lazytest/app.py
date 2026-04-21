from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from rich.markup import escape
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, RichLog, Static

from lazytest.config import AppConfig, load_config
from lazytest.core_flow import build_and_run_test
from lazytest.ctest_discovery import discovery_command, parse_ctest_json
from lazytest.models import DiscoveredTest, TestStatus
from lazytest.process_utils import collect_command
from lazytest.search import filter_tests, preserve_selection
from lazytest.session import TestSession


@dataclass(frozen=True)
class StatusDisplay:
    marker: str
    style: str


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

    ListItem {
        height: 1;
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

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search tests by name, label, command, or working directory", id="search")
        yield Static("Discovering tests...", id="summary")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield ListView(id="tests")
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

    async def discover(self) -> None:
        output = self.query_one("#output", RichLog)
        output.write(f"$ {' '.join(discovery_command(self.config))}")
        result = await collect_command(discovery_command(self.config))
        if not result.ok:
            output.write(result.output)
            output.write(f"CTest discovery failed with exit code {result.returncode}")
            return
        try:
            tests = parse_ctest_json(result.output)
        except ValueError as exc:
            output.write(str(exc))
            return
        self.session = TestSession.from_tests(tests)
        await self.apply_filter(self.query_one("#search", Input).value, None)

    async def apply_filter(self, query: str, selected_name: str | None) -> None:
        self.visible_tests = filter_tests(self.session.tests, query)
        list_view = self.query_one("#tests", ListView)
        await list_view.clear()
        if not self.visible_tests:
            await list_view.append(ListItem(Label("No matches")))
        else:
            for test in self.visible_tests:
                await list_view.append(ListItem(Label(self.format_test(test))))
            index = preserve_selection(selected_name, self.visible_tests)
            if index is not None:
                list_view.index = index
        summary = self.query_one("#summary", Static)
        summary.update(f"{len(self.visible_tests)} visible / {len(self.session.tests)} total")

    def format_test(self, test: DiscoveredTest) -> str:
        display = STATUS_DISPLAYS[test.status]
        label_text = f"[{', '.join(test.labels)}]" if test.labels else ""
        labels = f" {escape(label_text)}" if label_text else ""
        return f"[{display.style}]{display.marker} {escape(test.name)}{labels}[/]"

    def selected_test_name(self) -> str | None:
        list_view = self.query_one("#tests", ListView)
        if list_view.index is None or list_view.index >= len(self.visible_tests):
            return None
        return self.visible_tests[list_view.index].name

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_clear_search(self) -> None:
        self.query_one("#search", Input).value = ""

    def action_clear_output(self) -> None:
        self.query_one("#output", RichLog).clear()

    def action_refresh(self) -> None:
        self.run_worker(self.discover(), exclusive=True)

    def action_run_selected(self) -> None:
        name = self.selected_test_name()
        if name:
            self.run_tests_by_name([name])

    def action_run_failed(self) -> None:
        self.run_tests_by_name([test.name for test in self.session.failed_tests()])

    def action_run_all(self) -> None:
        self.run_tests_by_name([test.name for test in self.session.tests])

    @work(exclusive=True)
    async def run_tests_by_name(self, names: list[str]) -> None:
        await self._run_tests_by_name(names)

    async def _run_tests_by_name(self, names: list[str]) -> None:
        if not names:
            self.query_one("#output", RichLog).write("No tests selected.")
            return
        for name in names:
            test = self.session.tests_by_name.get(name)
            if test is None:
                continue
            self.session.set_status(name, TestStatus.RUNNING)
            await self.refresh_test_status(name)
            await build_and_run_test(self.config, self.session, test, self.append_output)
            await self.refresh_test_status(name)
            await asyncio.sleep(0)

    async def refresh_test_status(self, name: str) -> None:
        await self.apply_filter(self.query_one("#search", Input).value, name)

    async def append_output(self, text: str) -> None:
        self.query_one("#output", RichLog).write(text.rstrip("\n"))


def run() -> None:
    LazytestApp().run()
