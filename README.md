# lazytest

`lazytest` is a standalone terminal UI for CMake/CTest projects, especially C++ projects that register Catch2 tests with CTest. It discovers tests from CTest JSON, lets you filter by metadata, builds the configured owning target, then runs the selected test while streaming output.

## Design

The application is split so the UI stays thin:

- `lazytest/ctest_discovery.py`: invokes and parses `ctest --show-only=json-v1` output.
- `lazytest/search.py`: case-insensitive filtering and deterministic ranking.
- `lazytest/target_resolution.py`: maps a CTest test name to a CMake build target.
- `lazytest/cmake_build.py`: generates and runs `cmake --build`.
- `lazytest/test_runner.py`: generates and runs exact CTest selection commands.
- `lazytest/session.py`: tracks in-memory result state.
- `lazytest/app.py`: Textual terminal UI.

CTest does not generally expose the CMake target that owns each test. This MVP deliberately does not guess from source files or unsupported metadata. Configure regex mappings first, then optionally a default target.

## Project Structure

```text
lazytest/
  app.py
  cmake_build.py
  config.py
  core_flow.py
  ctest_discovery.py
  models.py
  process_utils.py
  search.py
  session.py
  target_resolution.py
  test_runner.py
tests/
example.lazytest.toml
main.py
pyproject.toml
```

## Configuration

You can configure the app in `[tool.lazytest]` inside `pyproject.toml`, or in a local `lazytest.toml`. A standalone example is included in `example.lazytest.toml`:

```toml
[lazytest]
build_dir = "build"
default_build_target = "all"

[[lazytest.target_mappings]]
pattern = "^unit\\."
target = "unit_tests"
```

For `pyproject.toml`, use `[[tool.lazytest.target_mappings]]` instead of `[[lazytest.target_mappings]]`.

Supported fields:

- `build_dir`
- `test_preset`
- `build_preset`
- `default_build_target`
- `target_mappings`
- `extra_ctest_args`
- `extra_build_args`

## Run

Install dependencies, then run:

```bash
uv sync
uv run lazytest
```

or:

```bash
python -m pip install -e '.[dev]'
python main.py
```

For a global-style install from this checkout:

```bash
uv tool install .
```

or:

```bash
python -m pip install .
```

Then run it from a CMake build directory:

```bash
cd /path/to/cmake/build
lazytest
```

If the current directory contains `CTestTestfile.cmake` or `Testing/`, `lazytest` treats `.` as the build directory. If not, it defaults to `build/` unless configured.

Keybindings:

- `/`: focus search
- `Ctrl+U`: clear search
- `Enter`: build and run selected test
- `f`: rerun failed tests
- `a`: run all tests
- `Ctrl+L`: clear output
- `r`: rediscover tests
- `Ctrl+Q`: quit

## Test

```bash
uv run pytest
```

or:

```bash
python -m pytest
```

## Limitations

- Discovery is intentionally CTest-based and does not parse C++ sources.
- Build target ownership must be configured with regex mappings or a default target. CTest JSON usually does not provide reliable target ownership.
- Test selection prefers `ctest --tests-from-file`. The command builder has an anchored `-R` fallback for older CTest versions, but that fallback is still regex-based.
- Statuses are preserved only in memory during the TUI session.
