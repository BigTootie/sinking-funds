# Savings Funds

Savings Funds is a personal finance app for tracking savings goals and a simple
monthly budget. It is built with Python and Flet and runs as a desktop, mobile,
or web app. See [`CHANGELOG.md`](CHANGELOG.md) for release notes.

## What it does

- Track savings funds with a target, current balance, optional target date, and
  recurring monthly contribution.
- Track monthly income and expenses, including each item's expected/budgeted
  amount and current received/spent amount.
- Automatically include each nonzero fund contribution as a budget expense.
  The generated expense follows the fund's contribution and is removed when the
  contribution becomes zero or the fund is deleted.
- Archive the budget at the end of each month and reset the spent amounts
  automatically. A manual **Reset month** action archives the current snapshot
  and starts the current month over.
- Track accounts and transactions in a local SQLite ledger, including transfers,
  cleared balances, search, filters, and undo after deletion.
- Export ledger data as CSV or JSON and import a JSON ledger snapshot.
- Switch between a blue-accented dark theme and a clean light theme in Settings.
- Optionally synchronize account/fund/budget totals with Nextcloud.

The bottom navigation opens Budget, Savings, and Transactions. The budget page
uses a clean EveryDollar-inspired list with a right-side monthly summary. Fund
cards and budget rows can be reordered. Use the plus and minus controls to
adjust actual amounts; editing a row lets you change its details. Destructive
actions ask for confirmation.

## Run the app

Install [uv](https://docs.astral.sh/uv/) and run the app from the project root:

```bash
uv run flet run
```

To run it in a browser:

```bash
uv run flet run --web
```

On first launch, the app asks for an account balance and offers optional
Nextcloud setup. Select Skip to use the app without synchronization. The
Nextcloud URL field expects a host name, such as `cloud.example.com`.

## Local data

`flet run` and packaged builds provide a durable per-app data directory through
`FLET_APP_STORAGE_DATA`. The app stores its files there. When that variable is
not set, for example when running `python src/main.py` directly, the app uses
the platform user-data directory (`platformdirs`) instead of the working
directory. Settings includes an **Open data folder** action.

On startup the app copies any legacy data files from the project root into the
configured data directory once, when the destination file does not already
exist. Existing data always wins; migration never overwrites it.

| File | Contents |
| --- | --- |
| `balance.txt` | Current account balance |
| `funds.json` | Savings funds with stable IDs, targets, balances, dates, and contributions |
| `budget.json` | Current budget period, income/expense items, and budgeted/current amounts |
| `budget_history.json` | Archived budget periods created by rollover or manual reset |
| `ledger.db` | Local SQLite accounts and transaction register |
| `nextcloud_sync.json` | Nextcloud connection settings (password stored separately) |
| `sync_state.json` | Last synchronized content hashes and ETags |

The JSON files use schema version 3 and stable fund/category IDs. Older
unversioned funds and budget files are still read automatically. Existing
balances and budget/fund totals are imported once into the local ledger as a
dated opening balance and migration records. New account balances are derived
from ledger transactions.

Data is written atomically. Before a file is replaced, a rolling copy is kept in
`backups/` (the ten most recent backups per file). Damaged files are never
silently replaced: they are moved to a `*.corrupt-*` file, and the app reports
the problem. Data files and the Nextcloud settings file use private
permissions where the platform supports them.

The Nextcloud password is stored in the operating system keyring when one is
available (Windows Credential Manager, macOS Keychain, or Linux Secret
Service/KWallet). Existing plaintext passwords are migrated automatically.
On systems without a keyring, the app falls back to the private
`nextcloud_sync.json` file and shows a warning.

When `nextcloud_sync.json` is present, synchronization is enabled until it is
disabled from Settings. Local data remains usable when Nextcloud is offline.

## Synchronization

When configured, the app downloads the data files at startup and uploads local
changes in the background. Every remote file is fetched and validated before
any local file is changed, so a network or validation failure cannot leave a
half-synced data set.

A content hash plus the server's ETag determines which copy changed. If both
copies changed, the remote copy is preserved as
`<file>.remote-<timestamp>.conflict`, the local copy is kept, and the local copy
is uploaded. Local files that cannot be read are preserved as
`*.corrupt-*` before a valid remote copy is restored. If the remote file is
missing, the app creates/uploads an empty file when both sides are empty, or
uploads the existing local file.

Uploads are debounced and serialized so a burst of edits sends each file once,
in order, and a new edit made during an upload is sent afterward. A failed
upload stays local and is retried after the next local change or the next app
start. A remote conflict asks you to restart so the next startup can reconcile
both copies. Disabling synchronization from Settings leaves all local data in
place and stops further uploads.

## Project structure

- `src/app.py` coordinates startup, persistence, page composition, and sync.
- `src/main.py` initializes durable storage before the data modules load.
- `src/paths.py` resolves the data directory and migrates legacy files.
- `src/ui/savings.py` contains savings dialogs, cards, and the dashboard.
- `src/ui/budget.py` contains budget dialogs, cards, and the dashboard.
- `src/ui/settings.py` contains the header and Nextcloud settings screen.
- `src/ui/navigation.py` handles switching between pages.
- `src/ui/shared.py` contains dialogs shared across pages.
- `src/fund.py` and `src/budget.py` hold the savings and budget models.
- `src/data.py` handles atomic persistence, backups, schema migration, and budget history.
- `src/nextcloud.py` handles WebDAV, reconciliation, conflicts, and sync state.
- `src/colors.py` and `src/utils.py` contain shared presentation and money helpers.
- `tests/` contains model, persistence, synchronization, startup, and UI tests.

## Tests and checks

Run the complete test suite, including the UI tests, with:

```bash
uv run pytest
```

The UI tests drive the real Flet controls with a headless page, so they do not
require Flutter or a display server. They use temporary files and stub the
Nextcloud server check, so they never read or write the real data directory.

Run the local checks with:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run python -m compileall -q src tests
```

## Build packages

Flet can build packages for Android, iOS, macOS, Linux, Windows, and the web.
For example, build a Linux package with:

```bash
uv run flet build linux -v
```

For a standalone desktop executable without running the Flutter build pipeline:

```bash
uv run --with pyinstaller flet pack src/main.py -n SavingsFunds
```

See the [Flet packaging guides](https://docs.flet.dev/publish/) for platform
requirements and signing instructions.
