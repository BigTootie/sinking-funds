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
- Synchronize accounts, transactions, funds, budgets, history, and
  contributions across devices through app-managed operation logs and snapshots
  on Nextcloud. The local database is never uploaded.
- Keep Nextcloud credentials in the local database and optionally encrypt
  synced data end to end with a passphrase or recovery key.

The bottom navigation opens Budget, Savings, and Transactions. The budget page
uses a clean EveryDollar-inspired list with a right-side monthly summary on
desktop and stacked, compact rows on phones. Fund cards and budget rows can be
reordered. Use the plus and minus controls to adjust actual amounts; editing a
row lets you change its details. Destructive actions ask for confirmation. The
Budget, Savings, Transactions, Settings, headers, and dialogs adapt to phone
widths without changing the desktop layout above 600 px.

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
`FLET_APP_STORAGE_DATA`. When that variable is not set, for example when running
`python src/main.py` directly, the app uses the platform user-data directory
(`platformdirs`). Settings includes an **Open data folder** action.

**SQLite is the only runtime data store.** Accounts, transactions, funds,
budget groups, per-month allocations, history, scheduled contributions,
settings, Nextcloud configuration, sync cursors, conflicts, and the operation
log all live in one `ledger.db` file. Money is stored as integer minor units
(cents) and as `Decimal` in memory. Writes are transactional, WAL is enabled,
and schema migrations are tracked in both `PRAGMA user_version` and a
`migrations` table.

The app does not read or migrate `balance.txt`, `funds.json`, `budget.json`,
`budget_history.json`, `nextcloud_sync.json`, or `sync_state.json`. Those legacy
files are not part of the v0.5 data model.

The only other local files are explicit user actions:

- `backups/database-*.db` for local recovery (the latest ten are retained);
- `exports/savings-funds-*.db` for portable exports;
- temporary SQLite `-wal` and `-shm` files while the database is open.

The Nextcloud password and optional encryption key are stored in the local
`ledger.db` database. They are never written to logs or Nextcloud, and settings
are device-local. Because database backups and explicit exports are complete
snapshots, protect those files as sensitive data. OS keyring integration is not
used in v0.5.

## Synchronization

v0.5 uses an operation-log protocol. Each device has a stable ID and writes an
ordered, checksummed operation document. Synchronization runs automatically on
startup and after local changes; Settings provides **Sync now** for manual
retries and **Review conflicts** when concurrent edits need a decision.

Remote layout is deliberately small:

- `sync-v1/manifest.json` — protocol and non-secret encryption metadata;
- `sync-v1/devices/<device_id>/ops.jsonl` — that device's operation history;
- `sync-v1/snapshots/<device_id>/snapshot.json` — a bootstrap snapshot.

A new device loads a snapshot for its initial state, then applies later
operations from other devices. Snapshots are overwritten as they advance, so a
two-device setup normally uses one manifest, one operation file per device, and
one snapshot per device. The live `ledger.db` is never uploaded.

Concurrent edits to the same record are not silently merged. The incoming
operation is held locally and the record remains at the local value until the
user chooses **Keep local** or **Use remote**. Unrelated records continue to
sync. Recurring fund contributions use the shared `(fund_id, period)` identity,
so the same month is never posted twice across devices.

If encryption is enabled, the user creates a passphrase or recovery key on the
first device and enters it once on each additional device. The derived key is
kept in the local database so normal startups do not prompt again. Nextcloud
stores operation and snapshot contents as ciphertext; the small protocol
manifest is unencrypted metadata. Losing the passphrase/recovery key makes
remote encrypted data unrecoverable; local data remains usable.

## Project structure

- `src/app.py` coordinates startup, persistence, page composition, and sync.
- `src/main.py` initializes durable storage before the data modules load.
- `src/paths.py` resolves the data directory.
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
- `src/data.py` handles budget bridges, database backups, and portable exports.
- `src/nextcloud.py` provides local Nextcloud settings and connection checks.
- `src/sync/` contains the operation protocol, encryption, WebDAV/local
  providers, and the sync engine.
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
