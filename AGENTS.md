# Repository Guidelines

## Project Structure & Module Organization

`lazytest` is a Python 3.11+ Textual TUI for CMake/CTest projects. The console script is `lazytest = "lazytest.app:run"` and `main.py` is only a thin local entry point.

Core code lives in `lazytest/`: CTest discovery, search, target resolution, build command generation, process handling, session state, theme detection, and the Textual app. Tests live under `tests/`; keep non-UI behavior covered there and keep UI-specific tests focused on observable state.

## Build, Test, and Development Commands

- `uv sync`: install project and development dependencies.
- `uv run lazytest`: run the TUI from the checkout.
- `uv run pytest`: run the full test suite.
- `uv run python -m py_compile main.py lazytest/*.py tests/*.py`: quick syntax check.
- `python main.py`: run the app if dependencies are available in the active environment.

The project uses Hatchling via `pyproject.toml`. Do not document new required tools until they are configured there.

## Coding Style & Naming Conventions

Use standard Python style: 4-space indentation, `snake_case` functions, `UPPER_SNAKE_CASE` constants, and `PascalCase` classes. Prefer explicit names and small functions. Add type hints for public or cross-module interfaces.

Keep `app.py` focused on UI orchestration. Prefer shared helpers in existing modules for CTest parsing, process execution, target resolution, and command construction.

## Testing Guidelines

Use `pytest` for behavior changes. Name files `test_<module>.py` and test functions `test_<behavior>()`. Cover parsing, command construction, filtering, process cancellation, and state transitions with unit tests before widening UI tests.

Run `uv run pytest` before handing off changes. If a test cannot be run because it needs local CMake/CTest fixtures, state that explicitly.

## Commit & Pull Request Guidelines

Use short imperative commit subjects, for example `Fix executable grouping` or `Document abort shortcut`. Keep unrelated cleanup and behavior changes separate when practical.

Pull requests should include a concise summary, test results, and any known limitations. Avoid committing virtual environments, caches, build artifacts, or secrets; `.gitignore` already covers the common Python outputs.
