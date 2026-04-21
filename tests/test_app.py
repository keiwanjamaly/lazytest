from rich.text import Text
import pytest

from lazytest.app import LazytestApp
from lazytest.config import AppConfig
from lazytest.models import DiscoveredTest, TestStatus as Status
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


@pytest.mark.asyncio
async def test_run_tests_by_name_refreshes_running_status_before_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = LazytestApp(AppConfig())
    app.session = Session.from_tests([DiscoveredTest("unit.math")])
    refreshed_statuses: list[Status] = []

    async def fake_refresh_test_status(name: str) -> None:
        refreshed_statuses.append(app.session.tests_by_name[name].status)

    async def fake_build_and_run_test(config, session, test, on_output):
        assert session.tests_by_name[test.name].status is Status.RUNNING
        session.set_status(test.name, Status.PASSED)
        return True

    monkeypatch.setattr(app, "refresh_test_status", fake_refresh_test_status)
    monkeypatch.setattr("lazytest.app.build_and_run_test", fake_build_and_run_test)

    await app._run_tests_by_name(["unit.math"])

    assert refreshed_statuses == [Status.RUNNING, Status.PASSED]
