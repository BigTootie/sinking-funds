# Changelog

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
- Show fund budget rows with the remaining amount needed to reach the fund goal
  instead of the confusing planned-vs-spent difference.
- Lighten the dark theme to a neutral grey palette with blue accents.

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

### Quality

- Add a 70% coverage gate, pre-commit hooks, local lint/format/type/compile/test
  checks, and headless Flet UI tests.
- `ruff format --check`, `mypy`, Ruff, compileall, and the full offline suite pass.
- Smoke-tested the generated Linux standalone executable under Xvfb.
