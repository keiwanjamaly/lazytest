# Repository Guidelines

## Project Structure & Module Organization

This repository is a minimal Python application scaffold. The entry point is `main.py`, which defines `main()` and runs it under the standard `if __name__ == "__main__"` guard. Project metadata lives in `pyproject.toml`, and `.python-version` pins Python `3.14`.

There is no package directory or test suite yet. If the project grows, move reusable code into `lazytest/`, keep CLI startup code thin in `main.py`, and place tests under `tests/`.

## Build, Test, and Development Commands

- `python main.py`: run the application directly.
- `python -m py_compile main.py`: perform a quick syntax check without running the program.
- `uv run python main.py`: run through `uv` if you are using the project scaffold created by `uv`.
- `uv sync`: create or update the local virtual environment once dependencies are added to `pyproject.toml`.

No build backend, formatter, linter, or test command is configured yet. Add tools to `pyproject.toml` before documenting them as required.

## Coding Style & Naming Conventions

Use standard Python style: 4-space indentation, function names in `snake_case`, constants in `UPPER_SNAKE_CASE`, and classes in `PascalCase`. Keep top-level executable behavior inside `main()` or small helper functions so modules remain importable.

Prefer explicit names over abbreviations. Keep functions focused and add type hints when they clarify public interfaces.

## Testing Guidelines

There are no tests yet. When adding behavior beyond the current greeting, add `pytest` tests under `tests/`. Name test files `test_<module>.py` and test functions `test_<behavior>()`, for example `tests/test_main.py`.

Once `pytest` is added, use `uv run pytest` or `python -m pytest`. Cover normal behavior and edge cases for parsing, I/O, or branching logic.

## Commit & Pull Request Guidelines

This repository has no existing commits, so no local commit convention is established. Use short, imperative commit subjects such as `Add CLI entry point` or `Document repository guidelines`. Keep unrelated changes in separate commits.

Pull requests should include a brief summary, test results or an explanation when tests are not applicable, and links to related issues.

## Security & Configuration Tips

Do not commit virtual environments, build artifacts, caches, or secrets. `.gitignore` already excludes `.venv`, Python bytecode, and distribution outputs. Keep local configuration in ignored files or environment variables.
