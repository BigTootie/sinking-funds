# Changelog

## 0.5.0 — 2026-10-30

### Multi-device sync v2

- Add an append-only device operation log with Lamport ordering, checksums,
  per-device cursors, and idempotent replay.
- Add compact per-device operation documents and snapshots over Nextcloud
  WebDAV, plus a local-folder provider for tests and LAN-style setups.
- Sync automatically after startup and local changes, with manual retry when a
  sync fails.
- Block conflicting edits instead of overwriting either side. Conflicts remain
  local until the user chooses **Keep local** or **Use remote** in Settings.
- Deduplicate recurring fund contributions across devices with the existing
  `(fund_id, period)` identity, including offline catch-up cases.
- Add optional end-to-end encryption using a user passphrase or recovery key,
  AES-GCM payloads, and a key stored in the OS keyring.
- Add sync status, last-sync/error reporting, device cursors, and conflict
  review to Settings.
- Ensure Nextcloud failures, invalid documents, checksum mismatches, and
  unsupported protocol versions fail safely without corrupting local data.

### One local data file

- Remove all legacy `balance.txt`, `funds.json`, `budget.json`,
  `budget_history.json`, `nextcloud_sync.json`, and `sync_state.json` support,
  including startup copying and JSON migration.
- Keep `ledger.db` as the only runtime data store. SQLite WAL files are
  temporary, and backups/exports remain explicit user actions.
- Store sync state, cursors, conflicts, and operation history in the same
  database. No local JSONL cache or live database file is uploaded.
- Prune database backups to the latest ten files.

### Quality

- Add protocol, encryption, local-provider, WebDAV request, two-device merge,
  conflict, snapshot, auto-post deduplication, and sync UI tests.
- Keep Ruff, formatting, mypy, compileall, and the full offline suite green.

## 0.4.0 — 2026-10-30

### Single-database storage

- Move all runtime data into the local SQLite database: accounts,
  transactions, funds, budget groups, per-month budget allocations, budget
  history, scheduled fund contributions, settings, Nextcloud configuration and
  sync state, and the operation-log foundation.
- Add schema v2 migrations with WAL, transactional writes, `PRAGMA
  user_version`, and a migration metadata table.
- Keep integer minor units for money in SQLite and `Decimal` in memory.
- Import legacy `balance.txt`, `funds.json`, `budget.json`,
  `budget_history.json`, and `nextcloud_sync.json` once. JSON remains only a
  migration/import/export format, not runtime storage.
- Add consistent SQLite backups and database export/restore.

### Budget engine

- Add category groups and per-month allocations with planned vs. actual
  amounts, “to be budgeted”, month navigation, copy-plan-forward, and archived
  history.
- Preserve the EveryDollar-style budget layout and dark/light themes while
  loading plans from SQLite.

### Funds and scheduled contributions

- Extend funds with kind, due day (1–31, defaulting to month-end clamping),
  priority, status, source/destination account references, and notes.
- Auto-post due monthly fund contributions idempotently by `(fund_id, period)`,
  catching up only the current occurrence and never backfilling past months.
- Show posted contributions in the ledger register, allow overdraft when an
  explicit destination account is configured, and support undo.
- Treat one-off fund contributions as budget-excluded savings transfers that do
  not reduce “to be budgeted”.
- Present funds as compact cards with budget-style drag handles and direct
  add/remove balance controls.
- Add an append-only `sync_ops` table and per-device Lamport counter as the
  foundation for v0.5 synchronization.

### Nextcloud

- Store non-secret Nextcloud settings and sync state in SQLite and keep the
  password in the OS keyring.
- Retire whole-file WebDAV synchronization from the runtime flow because JSON
  is no longer the source of truth. Multi-device operation-log sync is deferred
  to v0.5 and documented in the README.

### Quality

- Add SQLite migration, budget/TBB, due-date, auto-post idempotency, one-off
  contribution, undo, and headless UI tests.
- Keep Ruff, formatting, mypy, compileall, and the full offline suite green.

## 0.3.0 — 2026-10-29

### Local ledger

- Add a local SQLite ledger with accounts, transactions, transfers, and schema
  migrations.
- Derive account balances and cleared balances from ledger transactions.
- Add account creation/editing and opening balances.
- Add transaction add/edit/delete, dates, payee, memo, category, account,
  cleared state, transfers, search, filters, and undo after deletion.
- Import the existing account balance, funds, and budget totals into the ledger
  once, with an opening balance transaction and migration records.
- Keep the savings and budget dashboards working while account totals come from
  the ledger.

### UI

- Rework the budget page into a cleaner EveryDollar-inspired layout with a
  monthly summary panel, compact budget rows, planned/remaining columns, and a
  progress ring.
- Add a blue-accented light theme and a dark/light toggle in Settings.
- Add a Transactions page with account cards, register, search, filters, and
  CSV/JSON export plus JSON import.
- Improve the savings page styling through the shared semantic theme.
- Calculate “left to budget” from planned income minus planned expenses so
  planned-only rows update both the top banner and summary panel.
- Refresh the transaction register immediately after savings-balance changes
  and transaction edits.
- Treat the migrated default account as a Savings account instead of Checking.
- Append newly created budget items to the end of their list.
- Add spacing between fund cards, bound savings scrolling, and fix budget
  summary clipping at the right edge.
- Await the manual Nextcloud sync handler correctly.
- Make snackbars dismiss automatically and close immediately when their action is
  used.
- Recalculate savings and budget layout dimensions on the actual Flet window
  resize event.
- Compact fund cards and support drag-and-drop reordering plus move up/down
  actions.
- Show fund budget rows with the remaining amount needed to reach the fund goal
  instead of the confusing planned-vs-spent difference.
- Lighten the dark theme to a neutral grey palette with blue accents.
- Record account opening balances and balance edits as ledger transactions, and
  allow accounts to be deleted from the account editor.
- Clean up the Settings cards so Nextcloud and data actions use compact menus.

### Notes

- Real-user dataset migration validation was deferred for this release;
  automated migration fixtures cover representative data.

### Quality

- Add SQLite ledger tests, migration tests, register UI tests, and theme tests.
- Keep the full offline suite, Ruff, formatting, and mypy checks green.

## 0.2.0 — 2026-10-28

### Data safety

- Persist money as decimal strings with stable fund and category IDs.
- Support signed balances, spending, and fund overdrafts.
- Add schema v3 migration, newer-schema protection, and corruption quarantine.
- Make month rollover idempotent and run it on resume while the app is open.
- Preserve spending when a fund is deleted or its recurring contribution is
  zeroed; generated budget rows are read-only.
- Roll back in-memory state when a save fails.

### Backup and restore

- Add full local backups, zip export, and restore-latest-backup flows.
- Validate every restored file and create a safety snapshot first.
- Keep backup directories private and traversable (`0700`) with `0600` files.
- Repair legacy backup-directory permissions before scanning or restoring.
- Report unreadable backup files with an actionable error.

### Nextcloud synchronization

- Store the Nextcloud password in the OS keyring when available.
- Migrate existing plaintext passwords and remove plaintext config backups.
- Fall back to the private settings file with a visible warning when no keyring
  backend exists.
- Re-check remote content after `412` responses so stale/rotated ETags do not
  create false conflicts.
- Keep real remote conflicts preserved for restart reconciliation.
- Redact the Nextcloud password from request error messages.
- Remove the GitHub Actions workflow and Dependabot; checks run locally.

### UI and platform

- Fix invisible Flet dialogs caused by tight `Column` layouts around
  `TextField` controls.
- Add first-run balance skipping and Nextcloud setup timeout/dismissal.
- Add target-date clearing and past-date support.
- Add a `platformdirs` fallback for non-Flet launches.
- Add an **Open data folder** action in Settings.
- Add a native standalone Linux executable build path with `flet pack`.

### Notes

- Real-user dataset migration validation was deferred for this release;
  automated migration fixtures cover representative data.

### Quality

- Add a 70% coverage gate, pre-commit hooks, local lint/format/type/compile/test
  checks, and headless Flet UI tests.
- `ruff format --check`, `mypy`, Ruff, compileall, and the full offline suite pass.
- Smoke-tested the generated Linux standalone executable under Xvfb.
