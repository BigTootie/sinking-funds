# Changelog

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
