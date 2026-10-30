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
- `src/paths.py`: resolves the durable `FLET_APP_STORAGE_DATA` directory.
- `src/ui/`: reusable pages, dialogs, cards, navigation, and presentation. `shared.py` holds cross-page dialogs; `transactions.py` holds the ledger register.
- `src/ledger.py`: the single runtime SQLite database: accounts, transactions, funds, budget groups/allocations/history, contributions, settings, Nextcloud configuration/state, operation log, cursors, and conflicts.
- `src/data.py`: budget bridges, database backups, portable exports, and schema helpers.
- `src/nextcloud.py`: keyring-backed Nextcloud settings and connectivity checks.
- `src/sync/`: operation protocol, optional encryption, WebDAV/local providers, and sync engine.
- `src/fund.py` and `src/budget.py`: models and pure calculations.
- `src/utils.py`: money parsing/formatting; `src/colors.py`: shared styling.
- `tests/`: offline model/persistence/sync/startup tests plus headless Flet UI tests.

Treat this list as guidance; the implementation in the repository is authoritative.

## Data safety
- Money is represented with `Decimal` in memory. Parse user input through `parse_money`.
- Funds and budget categories have stable UUID identifiers. Do not key persistent behavior on names.
- Persist runtime data through ledger.py SQLite transactions. `ledger.db` is the only runtime data store; JSON files are explicit user import/export only.
- Do not add support for legacy data files (`balance.txt`, `funds.json`, `budget.json`, `budget_history.json`, `nextcloud_sync.json`, or `sync_state.json`).
- Preserve incompatible or damaged data by quarantining or backing it up before replacing it.
- Never overwrite real user data during tests. Patch the data path constants to `tmp_path`.
- Never hard-code credentials or log secrets. Nextcloud non-secret settings live in SQLite; the password lives in the OS keyring.
- Budget periods roll over on startup. Archives live in the SQLite `budget_history` table.
- The single SQLite database is local-only. Do not sync a live `ledger.db`; use operation logs/snapshots or database backup/export for portability.

## Synchronization
- Sync uses the operation log and snapshots in `src/sync/`; never sync a live SQLite file.
- Nextcloud settings/state live in SQLite; the password and optional encryption key live in the OS keyring.
- Block conflicting edits until the user resolves them; do not silently overwrite either side.
- Keep blocking network calls off the UI event loop and never log secrets.

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

## Releases
- Release page titles use exactly the version tag, such as `v0.5.0`.
- Squash-merge the release branch into `main`, tag `vX.Y.Z` on `main`, push
  both, and publish release notes from `CHANGELOG.md`.
- After the merge is pushed, delete the merged development branch locally and
  from `origin`.

## Workflow
1. Understand the requested behavior.
2. Inspect the relevant code and identify affected files.
3. Explain significant design choices before broad refactoring.
4. Implement the smallest complete solution.
5. Run appropriate tests and checks.
6. Review the diff.
7. Report changed files, behavior, test results, and remaining risks.

Ask before destructive operations, major architectural changes, or changes that could overwrite important data.
