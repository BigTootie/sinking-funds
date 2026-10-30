# Savings Funds

Savings Funds is a personal finance app for tracking savings goals and a simple
monthly budget. It is built with Python and Flet and runs as a desktop, mobile,
or web app. See [`CHANGELOG.md`](CHANGELOG.md) for release notes.

## What it does

- Track savings funds (earmarks/envelopes rather than bank accounts) with a
  target, balance, optional target date, priority, monthly contribution, and a
  selectable monthly due day (1–31, clamped to the end of shorter months).
- Track category-grouped monthly income and expenses with planned amounts,
  actual/current amounts, “to be budgeted”, month navigation, plan copying, and
  archived budget history.
- Automatically post due recurring fund contributions once per calendar month.
  Posting is idempotent per fund/period, catches up only the current occurrence,
  is visible in the register, allows overdrafts for configured destination
  accounts, and can be undone.
- Record one-off fund contributions. They are savings transfers, visibly
  budget-excluded, and do not reduce “to be budgeted”.
- Track accounts and transactions in the same local SQLite database as funds and
  budgets, including transfers, cleared balances, search, filters, and undo
  after deletion.
- Export ledger data as CSV or JSON and import a JSON ledger snapshot.
- Switch between a blue-accented dark theme and a clean light theme in Settings.
- Store Nextcloud connection settings and sync state locally. Multi-device
  synchronization is deferred to v0.5 while the operation-log sync protocol is
  built; v0.4 never reads or writes remote files.

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

**SQLite is the source of truth.** Accounts, transactions, funds, budget
groups, per-month allocations, budget history, scheduled fund contributions,
settings, Nextcloud configuration/state, and the operation-log foundation all
live in one `ledger.db` file. Money is stored as integer minor units (cents) in
SQLite and as `Decimal` in memory, so totals remain exact. Writes are
transactional, WAL is enabled, and schema migrations are tracked in both
`PRAGMA user_version` and a `migrations` table.

JSON and text files are **not runtime storage**. They may be present only as:

- one-time migration sources (`balance.txt`, `funds.json`, `budget.json`,
  `budget_history.json`, and a legacy `nextcloud_sync.json`);
- explicit import/export formats such as ledger JSON/CSV and database backups
  or exports.

After the first launch on v0.4, the app reads and writes only the database.
Legacy files are left untouched rather than deleted.

Backups use SQLite's consistent backup API and are written under `backups/` in
the data directory. Export writes a portable `.db` snapshot. Damaged legacy
files are still preserved as `*.corrupt-*` during migration instead of being
silently replaced. Data files use private permissions where the platform
supports them.

The Nextcloud password is stored in the operating system keyring when one is
available (Windows Credential Manager, macOS Keychain, or Linux Secret
Service/KWallet). The connection URL, username, data path, and sync state are
stored in SQLite; the password is never written to the database or logs. On
systems without a keyring, the app keeps the non-secret settings but warns that
the password cannot be saved until a keyring backend is available.

## Synchronization

v0.4 keeps the Nextcloud settings and sync-state storage in SQLite but **does
not perform multi-device file synchronization**. The v0.3 whole-file WebDAV
synchronizer is retired from the application flow because JSON files are no
longer the runtime source of truth. The database includes an append-only
`sync_ops` table and a per-device Lamport counter as the foundation for the v0.5
operation-log protocol; v0.5 will add snapshots, replay, conflict resolution,
and auto-post deduplication across devices. No live database file is ever
uploaded to Nextcloud.

Local data remains fully usable offline. Disabling Nextcloud from Settings
removes the saved connection settings and keyring password.

## Project structure

- `src/app.py` coordinates startup, persistence, page composition, and sync.
- `src/main.py` initializes durable storage before the data modules load.
- `src/paths.py` resolves the data directory and migrates legacy files.
- `src/ui/savings.py` contains savings dialogs, cards, and the dashboard.
- `src/ui/budget.py` contains budget dialogs, cards, and the dashboard.
- `src/ui/settings.py` contains the header and Nextcloud settings screen.
- `src/ui/navigation.py` handles switching between pages.
- `src/ui/shared.py` contains dialogs shared across pages.
- `src/fund.py` and `src/budget.py` hold the savings, due-date, group, and
  budget models.
- `src/ledger.py` owns the single SQLite database: schema/migrations, accounts,
  transactions, funds, per-month budget allocations, history, settings,
  fund contributions, and the operation log.
- `src/data.py` handles legacy JSON migration, import/export helpers, database
  backups, and compatibility parsers.
- `src/nextcloud.py` retains the legacy WebDAV implementation and provides
  keyring-backed Nextcloud settings stored in SQLite.
- `src/colors.py` and `src/utils.py` contain shared presentation and money helpers.
- `tests/` contains model, SQLite migration, budget/fund, ledger, startup, and
  headless UI tests.

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
