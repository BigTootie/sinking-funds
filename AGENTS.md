# Project Instructions

## Project overview
This is a Python savings-funds application built with Flet. It manages savings funds, account balances, monthly budgets, and optional synchronization with Nextcloud.

## Technology choices
- Keep Python as the primary language and Flet as the UI framework.
- Use `uv` for Python dependencies and commands.
- Preserve the existing Flet version and dependencies unless a change is necessary and justified.
- Do not migrate frameworks or rewrite the application without explicit approval.
- Avoid adding dependencies unless they provide clear value.

## Architecture
Inspect the actual repository before making changes. Preserve the existing separation of responsibilities:
- `src/app.py`: application initialization, startup flow, persistence coordination, and background synchronization.
- `src/main.py`: resolves durable storage before importing modules that bind data paths.
- `src/paths.py`: resolves `FLET_APP_STORAGE_DATA` (falling back to the working directory) and migrates legacy data.
- `src/ui/`: reusable pages, dialogs, cards, navigation, and presentation. `shared.py` holds cross-page dialogs.
- `src/data.py`: atomic local persistence, backups, quarantine, schema loading, and budget history.
- `src/nextcloud.py`: Nextcloud WebDAV, validation, reconciliation, conflict copies, and sync state.
- `src/fund.py` and `src/budget.py`: models and pure calculations.
- `src/utils.py`: money parsing/formatting; `src/colors.py`: shared styling.
- `tests/`: offline model/persistence/sync/startup tests plus headless Flet UI tests.

Treat this list as guidance; the implementation in the repository is authoritative.

## Data safety
- Money is represented with `Decimal` in memory. Parse user input through `parse_money`.
- Funds and budget categories have stable UUID identifiers. Do not key persistent behavior on names.
- Persist through the atomic write helpers in `data.py`; do not write data files directly.
- Preserve incompatible or damaged data by quarantining or backing it up before replacing it.
- Never overwrite real user data during tests. Patch the data path constants to `tmp_path`.
- Keep `nextcloud_sync.json` private. Store the Nextcloud password in the OS keyring when available, with the private-file fallback only when it is not. Never hard-code credentials or log secrets.
- Budget periods roll over on startup. Archives belong in `budget_history.json`.

## Synchronization
- Keep blocking network calls off the UI event loop.
- Fetch and validate every remote file before applying any of them.
- Use content hashes and ETags to decide whether to download or upload.
- Preserve conflicting remote copies instead of overwriting them silently.
- Keep uploads serialized and debounced; avoid duplicate concurrent uploads for the same file.
- A failed upload must remain local and be retried later; never drop it silently.
- Missing remote files and offline startup must not prevent access to local data.

## Implementation
- Make focused, minimal changes.
- Reuse existing components and conventions.
- Preserve dark mode, responsive layouts, and existing behavior.
- Handle errors clearly and avoid duplicate synchronization operations.
- Do not discard unrelated user changes.

## Verification
- Inspect existing tests and project configuration before choosing a test strategy.
- Use `uv run` for Python commands.
- Run `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run mypy src`, `uv run python -m compileall -q src tests`, and `uv run pytest` after implementation.
- Run UI tests as part of `uv run pytest`; they drive the Flet controls headlessly and do not require a Flutter host.
- Do not claim a test passed unless you actually ran it.
- Review the final diff for accidental changes, regressions, and exposed secrets.

## Workflow
1. Understand the requested behavior.
2. Inspect the relevant code and identify affected files.
3. Explain significant design choices before broad refactoring.
4. Implement the smallest complete solution.
5. Run appropriate tests and checks.
6. Review the diff.
7. Report changed files, behavior, test results, and remaining risks.

Ask before destructive operations, major architectural changes, or changes that could overwrite important data.
