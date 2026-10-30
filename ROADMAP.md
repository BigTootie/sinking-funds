# Savings Funds — Product & Engineering Roadmap

> Status: working proposal. Last updated: 2026-10-28.
>
> This roadmap deliberately favors **self-hosters and power users first**.
> Mainstream onboarding, localization, and app-store polish come at the end.
> Bank synchronization is the last major integration, after everything else is
> trustworthy.

## 1. Vision

**A privacy-first, local-first personal finance app that anyone can own, inspect,
and self-host.**

Savings Funds should become the open-source answer to EveryDollar/YNAB-class
budgeting: zero-based monthly budgets, real accounts and transactions, deep
savings-goal tracking that feeds the budget, debt payoff, and useful reports —
with no subscription, no ads, no data harvesting, and synchronization on
infrastructure the user controls.

### Positioning

| | EveryDollar | Actual Budget | Firefly III | Savings Funds (today) | Savings Funds (target) |
|---|---|---|---|---|---|
| Open source | No | Yes (AGPL) | Yes (AGPL) | **Yes (GPL-3.0)** | Yes |
| Local-first / offline | Partial | Yes | No (server) | **Yes** | Yes |
| Self-hosted sync | No | Yes | Yes | **Nextcloud** | Nextcloud + optional sync server |
| Zero-based budgeting | Yes | Yes | Partial | **No** | Yes |
| Transactions / accounts | Yes | Yes | Yes (double-entry) | **No (single balance)** | Yes |
| Savings goals / sinking funds | Yes | Partial | Partial | **Partial** | **First-class** |
| Debt tools | Yes | No | Partial | No | Yes |
| Bank sync | Yes (paid) | Optional | Optional | No | **Last; optional** |
| E2E encryption | No | Yes | No | No | Yes |
| Linux desktop | No | Web/desktop | Web | **Yes** | Yes |
| Subscription | Yes | No | No | **No** | No |

**Wedge:** the best self-hosted, zero-based budgeting app with genuinely deep
savings-goal tracking. Do not try to match EveryDollar feature-for-feature in
year one.

**Non-goals for the first v1.0:** investment trading, tax filing, business
accounting, AI advice, a multi-tenant SaaS, and bank sync.

## 2. Locked product decisions

These decisions drive the rest of the document.

1. **Audience:** self-hosters and power users first. Mainstream users later.
2. **Product shape:** budgeting-first. The monthly budget is the home screen.
3. **Savings goals stay first-class.** Funds keep targets, target dates,
   priorities, recurring contributions, progress, and projections. They feed the
   budget rather than living in a separate silo.
4. **One budget impact per recurring contribution.** A fund's monthly recurring
   transfer is a monthly budget line. That is its only budget impact. The actual
   account movement is a linked transfer marked as excluded from budgeting.
5. **One-off contributions are unbudgeted for now.** Extra money added to a fund
   is allowed without a budget line. It is a savings transfer, not a budget
   expense, and it does not reduce unassigned money.
6. **Monthly transfers auto-post on their due date.** Auto-posting is
   idempotent, visible in the register, undoable, and safe across devices.
7. **Bank sync comes last.** CSV/OFX/QIF import ships first. Bank aggregation is
   a post-1.0 optional integration, if it is sustainable at all.
8. **The SQLite migration is confirmed.** SQLite is local, not hosted. Each
   device has its own local database. No database server, API server, or Docker
   is required. Nextcloud stores app-managed operation logs and snapshots, never
   a live database file. The one-time migration ships with automatic backup,
   dry-run, and export.
9. **Transactions can be allocated to a fund.** A recorded bank transaction can
   be assigned to a fund and pulled straight from that fund's balance. The
   transaction remains an expense in its spending category; the budget
   reallocates the amount from the fund's earmark to that category so it is not
   double-counted.
10. **Keep Flet for now.** Extract a pure-Python domain core so the UI can change
    later without a rewrite.
11. **Stay GPL-3.0 for now.** Decide on AGPL-3.0 before accepting outside
    contributions if a hosted web service is planned.

## 3. Where the project is today

### Strengths worth preserving

- Small, readable Python/Flet codebase (~2.4k source lines) with a clear
  separation between models, persistence, sync, and UI.
- Good data-safety instincts: atomic writes, fsync, rolling backups, quarantine
  of corrupt files, a schema version field, and conflict copies.
- Nextcloud WebDAV sync with content hashes + ETags, serialized/debounced
  uploads, retry-on-next-change, and tests for the hard cases.
- Responsive dark UI, reorderable lists, target dates, recurring fund
  contributions, and on-track calculations.
- Offline tests passing, including headless Flet UI tests; lint and compile
  checks run locally; GPL-3.0 license.

### The core limitation

The app stores **mutable totals**, not **money movements**:

- `balance.txt` is one aggregate account total.
- `funds.json` stores each fund's current balance.
- `budget.json` stores each category's budgeted and spent totals.
- Adjusting a fund or budget row rewrites that number. There is no transaction,
  date, payee, note, account, or audit trail.
- Fund contributions, budget spending, and the account balance are disconnected
  numbers. They drift because nothing forces them to reconcile.

Everything below flows from that. Reports, debt, bank import, household sync,
and user trust all require a ledger.

## 4. Gap analysis vs EveryDollar

| Capability | EveryDollar | Current app | Priority |
|---|---|---|---|
| Zero-based monthly budget ("to be budgeted") | Yes | No; static category budgets | **P0** |
| Per-month budget plans and history | Yes | One current-month template; history not viewable | **P0** |
| Accounts (checking, savings, cash, credit) | Yes | One aggregate balance | **P0** |
| Transaction register (payee, date, note, category) | Yes | No | **P0** |
| Transfers, splits, reconciliation | Yes | No | P1 |
| Savings goals / sinking funds | Yes | Partial: target + balance + monthly plan, not linked to money movement | **P0** |
| Recurring transfers into funds | Yes | Budget row only; no due date, no auto-post, no transfer | **P0** |
| Recurring transactions / bills | Yes | Only generated fund budget rows | P1 |
| Reports and charts | Yes | No; only progress bars | P1 |
| Debt snowball / payoff tools | Yes | No | P2 |
| Net worth | Yes | No | P2 |
| CSV/OFX/QIF import | Yes/partial | No | P1 |
| Bank sync | Yes (paid) | No | **Last** |
| Multi-device sync | Yes | Whole-file Nextcloud sync, local-wins conflicts | **P1** |
| Household sharing | Yes | No | P3 |
| Web + mobile + desktop | Yes | Flet cross-platform; mobile polish unproven | P1 |
| Localization / multi-currency | Yes | Hard-coded USD and US dates | P2 |
| Accessibility | Yes | Unknown; fixed-height cards and drag-only reorder are risks | P2 |
| App lock / encryption at rest | Yes | No | P1 |
| Attachments / receipts | Partial | No | P3 |
| Investments / retirement | No | No | P3 |
| Open source / self-host / no subscription | No | **Yes** | Differentiator |

## 5. Deficiency register

Severity: **P0** = data integrity, security, or blocks the product; **P1** =
major UX/feature gap; **P2** = scale, quality, or later-stage.

### P0 — Data integrity and correctness

1. **No ledger / no audit trail.** Balances and spent amounts are edited in
   place (`src/ui/savings.py`, `src/ui/budget.py`). There is no way to answer
   "why is this number what it is?", undo an edit, or reconcile.
2. **Funds, budget, and account balance are disconnected.** Adding $100 to a fund
   changes allocation but creates no budget activity; changing budget "spent"
   does not move the account balance.
3. **Budget is a single-month template.** `BudgetState` holds one category list
   and a period. Reset keeps the same budgeted amounts; there is no per-month
   plan, month navigation, or history UI. History is appended but never read.
4. **Rollover only happens at startup.** If the app stays open across a month
   boundary, the period does not roll until restart (`src/data.py:rollover_budget`,
   called only from `src/app.py` startup).
5. **Archive + save is not atomic across files.** `archive_budget` writes history,
   then the app writes `budget.json`. A failure in between can duplicate history
   or leave the budget un-rolled (`src/data.py:385-404`, `src/app.py:275-304`).
   Manual reset can append duplicate entries for the same period.
6. **Money is serialized as JSON floats.** `fund_to_dict` and `category_to_dict`
   use `float(...)`. Fine for typical cents, but not exact for large values and
   a poor long-term storage format. Store integer minor units or decimal strings.
7. **Negative money is impossible.** `parse_money` rejects negatives, so refunds,
   credit accounts, negative balances, overdrafts, and overspending corrections
   cannot be represented. Auto-posting a transfer can legitimately overdraw an
   account; the ledger must allow and display that.
8. **Generated budget rows can lose data.**
   - If a fund ID is regenerated on load (duplicate ID handling), the generated
     row's `source_fund_id` no longer matches and `sync_recurring_fund_expenses`
     removes the row, losing its spent amount (`src/data.py:202-205`,
     `src/budget.py:75-81`).
   - Deleting a fund or setting its contribution to zero removes the generated
     expense and its spending history (`src/budget.py`, covered by tests).
   - Users can edit a generated row's name/budget, but the next sync silently
     overwrites it back to the fund's values.
9. **No scheduled-transfer engine.** A fund's recurring contribution is only a
   budget row. There is no due date, no automatic transfer, no idempotency key,
   and no way to recover a missed occurrence.
10. **Partial sync apply on write failure.** All remote files are fetched and
    validated before applying, but files are written one at a time; a disk error
    midway leaves a partially applied set (`src/nextcloud.py:326-376`).
11. **Startup can hang.** With no Nextcloud config, `perform_nextcloud_sync`
    waits on an `asyncio.Event` forever (`src/app.py:102-105`); if the dialog is
    dismissed without "Skip" (e.g. Android back), startup never continues. The
    first-run balance dialog also has no skip/cancel (`src/ui/shared.py:103-134`).

### P0 — Security and privacy

12. **Nextcloud password protection depends on a working OS keyring.**
    Passwords are stored in the OS keyring when available, with automatic
    migration from older plaintext settings. Headless systems without a keyring
    still fall back to the private `nextcloud_sync.json` file and show a warning.
    E2E encryption is still not implemented.
13. **No app lock / encryption at rest.** Anyone with the device or a backup can
    read the financial data. This is table stakes for a finance app.
14. **No diagnostics/threat model.** Logs are not user-visible or consistently
    redacted; there is no privacy policy, disclosure process, or audit of what is
    sent to Nextcloud.

### P1 — UX, accessibility, and integrations

15. **Target date cannot be cleared.** The date picker only sets a date; there is
    no "clear" action, and `first_date=today` prevents editing past dates
    (`src/ui/savings.py:54-72`).
16. **Fixed card heights** (140/170/130 px) assume a font scale, one-line names,
    and English labels. Long names, large text, and translations will overflow
    (`src/ui/savings.py:14-15`, `src/ui/budget.py:18`).
17. **Dark-only, USD-only, US-date-only, English-only.** `money_format` hardcodes
    `$`; target dates use `%m/%d/%Y` (`src/utils.py`, `src/data.py`).
18. **No sync status or conflict UI.** Errors are transient snackbars; there is
    no last-synced time, manual sync, retry button, device list, or merge screen.
    Conflicts are written as `.conflict` files the user must find manually.
19. **Whole-file sync with local-wins conflicts.** Two devices editing different
    funds still conflict. No record-level merge, no tombstones, no device IDs.
20. **ETags are stored but not used for conditional GET.** Every startup
    downloads all four files (`src/nextcloud.py:282-307`).
21. **Nextcloud compatibility gaps:** subdirectory installs are rejected
    (`normalize_base_url` allows host only), self-signed/private CA certificates
    are unsupported, and the data folder must already exist (no MKCOL).
22. **No import/export UI.** The JSON files are hidden; there is no CSV/OFX
    import, no export, no backup/restore screen, no print/PDF.
23. **No search, filter, undo, or trash.** Destructive actions are permanent after
    a confirmation dialog.
24. **No reports or history views.** Budget history and fund progress are stored
    but not presented.
25. **No app lock, no biometrics, no auto-lock.**
26. **Mobile and accessibility are unverified.** UI tests are skipped in CI; the
    Flutter host is not part of the pipeline; drag-only reordering and fixed
    layouts are accessibility risks.

### P2 — Engineering, packaging, and scale

27. **JSON files, O(n) rewrites, no transactions.** `archive_budget` reads and
    rewrites the entire history on every reset; every edit rewrites the whole
    file. Fine for a year, painful for a decade.
28. **No migration framework.** `SCHEMA_VERSION` is written but never checked;
    there is no v1/v2/v3 migration path, no fixtures, no downgrade policy.
29. **Native packaging is partially proven.** A standalone Linux executable has
    been built and launched; platform installers, signing, and update behavior
    still need verification. Python package layout is intentionally not a goal.
30. **Quality gates are local-only.** Coverage, tests, lint, formatting, type
    checking, and pre-commit run locally; there is no hosted CI or security
    scanning.
31. **No release/community infrastructure.** No changelog, CONTRIBUTING,
    CODE_OF_CONDUCT, SECURITY.md, issue/PR templates, docs site, translation
    workflow, signed builds, auto-update, or funding model.
32. **Flet risk.** Flet is a good fit for the current app, but mobile polish,
    accessibility, store deployment, and long-term ecosystem support are
    unproven for a finance product. Mitigate by keeping the domain core
    UI-independent; do not rewrite the UI now.

## 6. Savings goals and fund contributions

This section is the contract between the savings feature and the budget. It
exists to prevent the current drift and to prevent double-counting.

### 6.1 Fund model

A fund is a savings envelope with a purpose. It can be:

- a **savings goal** with a target amount and optional target date, or
- a **sinking fund** for an irregular expense (car repair, insurance, holidays),
  with a target amount and a monthly set-aside.

Both share the same model:

- stable `fund_id`
- `name`, `kind` (`savings_goal` / `sinking_fund`)
- `target_amount`, `target_date`
- `monthly_contribution`
- `due_day` (1–31, used by auto-post)
- `source_account_id` (where money comes from)
- `destination_account_id` or fund bucket (where money goes)
- `priority`, `status` (`active` / `archived`)
- optional notes and icon/color
- projected completion date and on-track calculation

Fund balances are derived from transfers, never edited directly.

### 6.2 The monthly contribution rule

> A fund's recurring monthly contribution is a monthly budget line. That is its
> only budget impact. The linked account transfer is excluded from budgeting.

Each month:

1. The budget automatically contains one line for the fund:
   **`{Fund name} contribution`**, amount = `monthly_contribution`, under a
   **Savings** group.
2. That amount reduces the month's unassigned money **once**, when the budget is
   planned.
3. On `due_day`, the app auto-posts a **transfer** from the source account to the
   fund's destination.
4. The transfer is linked to the budget line and marked **budget-excluded**, so
   it cannot reduce the budget a second time.
5. The fund balance increases by the contribution. The account balances change,
   but net worth does not (it is an internal transfer).
6. In reports, the contribution is classified as **Savings**, not **Expense**.
   It affects savings rate and cash flow, not consumption.

Worked example:

```text
Income                          $5,000
Rent                           −$1,500
Food                             −$600
Emergency Fund contribution      −$300
Other expenses                 −$2,400
─────────────────────────────────────
Unassigned                       $200

Auto-post on the 15th:
  Checking        −$300
  Savings         +$300
  Fund balance    +$300
  Budget impact:   $0 (already counted above)
```

### 6.3 Auto-posting rules

- **Due date:** monthly, on `due_day`; clamp to the last day of shorter months
  (e.g. day 31 in February).
- **Trigger:** on app start and once per day while the app is running.
- **Idempotency:** every occurrence has a unique key, e.g.
  `(fund_id, period)`. A database unique constraint prevents duplicates.
- **Missed occurrences:** if the app was closed, post the current due occurrence
  on next launch. Do not silently backfill multiple past months; surface missed
  occurrences for review instead. *(Confirmed.)*
- **Insufficient funds:** post anyway, show a clear warning/overdraft, and never
  silently skip the transfer. The ledger must support negative account balances.
- **Visibility:** auto-posted transfers appear in the register with a link to the
  fund and budget line. They can be undone/reversed.
- **Changes:** changing a fund's monthly amount applies to the next unposted
  occurrence. If the current month has not posted yet, update the current line;
  otherwise leave the posted line and apply from next month. Never silently
  rewrite history.
- **Deletion:** archive the fund instead of deleting it. Posted lines and
  transfers stay in history; future lines are removed.
- **Multi-device:** the occurrence key makes auto-post idempotent across devices
  and across sync. If two devices post the same occurrence, exactly one wins.

### 6.4 One-off contributions

- Allowed without a budget line **for now**.
- Creates a transfer from the source account to the fund, marked
  `budget_excluded = true`.
- Does not reduce unassigned money.
- Appears in reports as a savings transfer and can be labelled "unbudgeted".
- The UI should make the distinction obvious so users do not assume it was
  budgeted.
- Later, an optional setting can require one-off contributions to be budgeted
  first; that is not v1 behavior.

### 6.5 Allocating a bank transaction to a fund

Confirmed behavior: a recorded bank transaction can be allocated to a fund and
pulled straight from that fund's balance.

- The transaction stays an **expense** in its real spending category (Auto,
  Home, Groceries, etc.). It is not reclassified as a savings contribution.
- Allocating it creates a **fund withdrawal** and reduces the fund balance by the
  transaction amount.
- Because the money was already committed to the fund when it was saved, the
  budget **reallocates** that amount from the fund's Savings category to the
  transaction's spending category. The net effect on unassigned money is zero;
  the expense is not counted twice.
- In reports, the transaction is consumption (an expense) exactly once. The
  earlier contribution was a savings transfer, not consumption.
- One transaction can be allocated to at most one fund for now; splits can come
  later.
- **Insufficient fund balance:** allow the allocation, mark the fund as
  overdrawn, and show a clear warning. The bank transaction already happened;
  silently refusing to record it would be worse.
- **Unallocate:** reverses the fund withdrawal and restores the budget
  reallocation. The transaction stays recorded either way.
- The register and transaction detail must show whether a transaction is
  **unallocated**, **funded by a fund**, or a **savings transfer**. This is the
  main defense against double counting.

Worked example:

```text
Fund balance before:                 $800
Car repair transaction (Auto):       $250
Allocate transaction to Car Fund:
  Car Fund balance                   $550
  Auto spending category             $250 (already recorded)
  Budget reallocation:
    Car Fund Savings category       −$250
    Auto category                   +$250
  Unassigned money                   $0 change
```

### 6.6 Budget-line ownership

The fund is the source of truth for the recurring amount. The generated budget
line is read-only in the budget with an **Edit fund** action. This fixes the
current bug where editing a generated line is silently reverted on the next sync.

## 7. Strategic decisions

| # | Decision | Status | Recommendation |
|---|---|---|---|
| 1 | Audience | **Locked** | Self-hosters/power users first; mainstream later. |
| 2 | Product shape | **Locked** | Budgeting-first, with first-class savings goals. |
| 3 | Fund contribution semantics | **Locked** | One monthly budget line; linked transfer excluded from budget. |
| 4 | One-off contributions | **Locked** | Allowed unbudgeted for now. |
| 5 | Auto-post | **Locked** | Monthly transfers auto-post on due date; idempotent. |
| 6 | Bank sync | **Locked** | Last, post-1.0, optional. |
| 7 | Data layer | **Locked** | SQLite, integer minor units, WAL, versioned migrations. |
| 8 | Sync architecture | Proposed | Per-device op log + snapshots over WebDAV; local SQLite only. |
| 9 | Platform | Proposed | Keep Flet; extract a pure-Python core; mobile spike early. |
| 10 | License | Open | GPL-3.0 now; decide AGPL before outside contributions. |
| 11 | Migration | **Locked** | One breaking migration to SQLite with backup, dry-run, export. |
| 12 | Transaction allocation | **Locked** | Allocate a bank transaction to a fund; reallocate from its earmark, no double count. |
| 13 | Primary platform | Open | Desktop vs Android vs web-first. |

## 8. Target architecture

```text
src/savings_funds/
  core/           # pure Python, no Flet/requests
    money.py      # integer minor units, parse/format, currency
    models.py     # Account, Transaction, Category, Budget, Fund, Debt
    ledger.py     # balances, transfers, reconciliation invariants
    budgeting.py  # TBB, allocations, rollover, overspend
    funds.py      # contribution schedules, projections, on-track math
    reports.py    # pure queries/aggregations
  storage/
    db.py         # SQLite connection, WAL, migrations
    repositories.py
    export.py     # JSON/CSV/OFX
  sync/
    protocol.py   # op log, snapshots, tombstones, device IDs
    webdav.py     # Nextcloud/WebDAV provider
    crypto.py     # E2E encryption (phase 2)
  scheduling/
    auto_post.py  # due-date engine, idempotency, catch-up
  ui/             # Flet pages and adapters only
  cli/            # headless import/export/repair
```

### Ledger schema sketch

- `accounts(id, name, type, currency, opening_balance_minor, archived)`
- `transactions(id, account_id, date, payee, memo, amount_minor, category_id,
  transfer_id, fund_id, budget_excluded, cleared, created_at, updated_at)`
- `categories(id, group_id, name, kind, rollover, archived)`
- `budget_allocations(id, period, category_id, amount_minor)`
- `funds(id, name, kind, target_minor, target_date, monthly_contribution_minor,
  due_day, source_account_id, destination_account_id, priority, status)`
- `scheduled_transfers(id, fund_id, due_day, amount_minor, next_due_date,
  last_posted_period, active)`
- `debts(id, name, balance_minor, apr, minimum_payment_minor, due_day)`
- `sync_ops(id, device_id, lamport, entity, entity_id, op, payload, created_at)`
- `meta(key, value)` for schema version, device ID, encryption salt.

**Rules:** every balance is derived; every change is a transaction or an
allocation; no UI writes a total directly. Amounts are integer minor units
(cents) plus a currency code. `Decimal` remains the in-memory type.

### Sync protocol sketch

- Each device appends operations to its own immutable segments:
  `devices/<device_id>/000042.jsonl` on WebDAV.
- A device downloads peers' segments, applies unseen ops idempotently, and
  records a cursor per peer.
- Ops carry `(device_id, lamport, entity, entity_id, op, payload)`; conflicts
  resolve per field by Lamport order, with tombstones for deletes.
- Periodic snapshots let a new device bootstrap quickly. Ops can be kept as an
  audit trail; pruning is opt-in.
- Auto-post uses the same op log. The `(fund_id, period)` unique key guarantees
  one posted occurrence even if two devices run the scheduler.
- E2E encryption wraps op payloads/snapshots with a key derived from a passphrase
  or recovery key; the key lives in the OS keyring. Nextcloud sees ciphertext.
- No live `.db` file is ever placed in Nextcloud/Dropbox/Syncthing. The database
  stays local; only app-managed op segments and snapshots sync.

## 9. Roadmap

Effort assumes one experienced developer full-time; multiply for part-time.
Phase gates are deliberate: do not start the next phase until the exit criteria
are met.

### Phase 0 — Trustworthy core (v0.2, ~3–5 weeks)

**Goal:** no known data-loss bugs; a foundation that can be migrated safely.

**v0.2.0 branch status (2026-10-28):**

- [x] Decimal-string persistence; signed balances, spending, and overdrafts.
- [x] Idempotent rollover, rollback when a save fails, resume/month watcher.
- [x] Generated budget rows are read-only; spending survives deleted/zeroed
  funds; duplicate IDs are quarantined instead of silently remapped.
- [x] Schema v3 migration framework with fixtures; newer schemas are preserved.
- [x] Full backup, zip export, and "restore latest backup" with validation and
  a safety snapshot.
- [x] First-run balance skip, Nextcloud setup timeout/dismissal.
- [x] Target-date clear and past-date support.
- [x] Coverage gate ≥70%, pre-commit, and local
  lint/format/type/compile/test checks.
- [x] Nextcloud password in the OS keyring with plaintext migration and a
  private-file fallback.
- [x] "Open data folder" and a `platformdirs` fallback for non-Flet launches.
- [x] `mypy` and `ruff format --check`.
- [x] Log redaction review.
- [x] v0.2.0 release notes, version bump, and native executable smoke test.

Python package layout and console entry points are no longer v0.2 goals; the
release target is native Flet packages for supported platforms. See
[`CHANGELOG.md`](CHANGELOG.md) for the 0.2.0 release notes.

- Store money as integer minor units or decimal strings; support negative amounts
  and overdrafts.
- Make budget rollover idempotent and run it on resume/month change, not only at
  startup; make archive + budget save a single recoverable operation.
- Protect generated budget rows; preserve spending when a fund is deleted or a
  contribution is zeroed; preserve fund IDs.
- Add a real migration framework (`user_version`, versioned migrations, fixtures).
- Add backup/restore and JSON export UI; add "restore from backup" and "open data
  folder".
- Fix first-run flow: optional balance skip, dialog dismissal, startup sync
  timeout/cancel.
- Fix target-date clear/past-date handling.
- Add a `platformdirs` fallback for non-Flet launches and an "open data folder"
  action. Python package layout is not required; ship native Flet packages.
- Quality: coverage ≥70%, `mypy`/`pyright`, `ruff format --check`, pre-commit,
  and the offline test suite.
- Security: Nextcloud password in the OS keyring where available; review log
  redaction.
- **Exit:** migration fixtures pass; no P0 data-loss bug; local checks green;
  v0.2.0 release with notes.

### Phase 1 — Local ledger (v0.3, ~8–12 weeks)

**Goal:** every dollar movement is recorded locally.

**v0.3.0 branch status (2026-10-29):**

- [x] SQLite ledger schema, repository, and schema migration.
- [x] Accounts with opening balances and derived current/cleared balances.
- [x] Transaction add/edit/delete with date, payee, memo, category, account,
  cleared state, search, filters, and undo.
- [x] Transfers between accounts.
- [x] One-time migration of existing balance/fund/budget totals.
- [x] Register and account management UI; budget and savings remain available.
- [x] CSV/JSON export and JSON import UI.
- [x] EveryDollar-inspired budget layout and light/dark theme toggle.
- [x] Property-based money tests and import fault-injection coverage.
- [x] Migration fixtures cover the current JSON sample data. Real-user dataset
  validation was deferred by the maintainer for this release.
- [x] v0.3.0 release notes and version bump.

- SQLite schema + repositories + migrations.
- Accounts (checking, savings, cash, credit) and opening balances.
- Transactions: add/edit/delete, date, payee, memo, category, account, cleared,
  search/filter, undo.
- Transfers between accounts; derived balances; reconciliation workflow.
- Migrate current `balance.txt`, funds, and budget totals into opening balances,
  fund balances, and dated adjustment transactions with a clear migration note.
- Register UI and account detail UI; keep the savings/budget dashboards as
  derived summaries.
- Export CSV/JSON from the UI; import JSON for restore.
- Tests: ledger invariants, property-based money tests, migration fixtures,
  crash-safety/fault injection.
- **Exit:** all balances derived; a user can record a month of transactions and
  reconcile; migration verified on real sample data; v0.3.

### Phase 2 — Budget and savings engine (v0.4, ~8–12 weeks)

**Goal:** a real zero-based budget with deep savings goals and safe auto-posting.

**v0.4.0 branch status (2026-10-29):**

- [x] One SQLite database for ledger, funds, budget groups/allocations/history,
  settings, Nextcloud configuration/state, and the operation-log foundation.
- [x] Category groups, per-month allocations, planned vs. actual, “to be
  budgeted”, month navigation, copy-plan-forward, and archived history.
- [x] Fund due day (1–31, month-end clamping), monthly contribution, priority,
  kind/status, and on-track fields.
- [x] Idempotent auto-post by `(fund_id, period)`, current-occurrence catch-up,
  register visibility, overdraft for explicit destination accounts, and undo.
- [x] One-off budget-excluded contributions.
- [x] Legacy JSON is migration/import/export only; consistent SQLite backups.
- [x] Operation-log table/design added; multi-device apply is deferred to v0.5.
- [x] Whole-file Nextcloud sync retired from the runtime flow; settings/state
  remain in SQLite pending sync v2.
- [x] Transaction-level classification distinguishes savings, expense,
  income, adjustments, and transfers.
- [ ] Full reports UI/templates and transaction-to-fund allocation remain future
  work.

- Per-month allocations per category; category groups; "to be budgeted";
  rollover rules; overspending handling (cash first, credit later).
- Month navigation, copy/plan next month, budget history UI, templates.
- Fund model: savings goals and sinking funds; target dates, priority, projected
  completion, on-track math.
- Monthly contribution lines under a Savings group; fund is the source of truth;
  generated lines are read-only with an Edit fund action.
- Auto-post engine: due dates, idempotency keys, catch-up rules, overdraft
  warnings, undo/reverse, visible register entries.
- One-off unbudgeted contributions; withdrawal/direct-spend rules with tests.
- Budget/report classification: Savings vs Expense; transfers excluded from both.
- Recurring/scheduled transaction foundation; monthly only at first.
- **Exit:** a user can run a full month from income to zero, auto-post fund
  contributions, record one-off contributions, view history, and reconcile to
  the ledger without double counting; v0.4.

### Phase 3 — Sync v2 (v0.5, ~8–14 weeks)

**Goal:** multi-device without data loss.

**v0.5.0 status (2026-10-30):**

- [x] Operation log, per-device cursors, checksums, snapshots, replay, and
  conflict blocking.
- [x] Compact Nextcloud layout: manifest, one operation file per device, and one
  snapshot per device.
- [x] Automatic sync after startup/local changes, manual retry, and sync status.
- [x] Conflicting edits remain local until the user chooses local or remote.
- [x] Auto-post deduplication across devices and offline catch-up.
- [x] Optional AES-GCM end-to-end encryption with keyring-backed passphrase or
  recovery key.
- [x] Local-folder provider, WebDAV retries/conditional writes, and adapter
  tests.
- [ ] E2E key rotation and recovery-key display flow remain future polish.
- [ ] Encryption migration for an existing unencrypted sync folder remains a
  documented limitation.


- Op log + snapshots over WebDAV; device IDs; idempotent apply; tombstones;
  compaction.
- Auto-post deduplication across devices and offline periods.
- Sync status UI: last synced, pending ops, manual sync, retry, device list,
  conflict resolution screen.
- Retry/backoff, conditional GET, subdirectory installs, self-signed/private CA,
  MKCOL folder creation.
- E2E encryption (optional passphrase/recovery key) with keyring storage.
- Provider abstraction; local-folder provider for tests and Syncthing-style
  setups.
- **Exit:** two devices edit offline concurrently and merge without loss; a
  scheduled transfer posted on both devices produces exactly one transaction;
  encrypted sync verified; fault-injection suite green; v0.5.

### Phase 4 — Reports and planning (v0.6, ~6–8 weeks)

**Goal:** answer "where did my money go?", "am I saving enough?", and "when am I
debt-free?".

- Reports: spending by category/group, income vs. expense, cash flow, savings
  rate, budget vs. actual, trends, net worth, fund progress and projections.
- Date ranges; CSV/PDF export; print-friendly views.
- Debt module: balances, APR, minimums, snowball/avalanche payoff simulation,
  payoff date and interest saved; link to accounts.
- Net worth: assets/liabilities, manual investment valuations.
- **Exit:** reports reconcile exactly to ledger; savings contributions are not
  counted as consumption; debt plan works; v0.6.

### Phase 5 — Import and automation (v0.7, ~8–12 weeks)

**Goal:** get real data in without hand-entry.

- CSV/OFX/QIF import with column mapping, preview, dedupe, and rules.
- Rules/auto-categorization (payee → category), bulk edit, splits, tags,
  attachments/receipts.
- Advanced recurrence: weekly/biweekly/semi-monthly, start/end dates, reminders.
- **No bank sync in this phase.**
- **Exit:** import a year of bank data, categorize with rules, reconcile; v0.7.

### Phase 6 — Self-hoster v1.0 (v1.0, ~6–10 weeks)

**Goal:** a power user can self-host, back up, restore, and trust it.

- CLI/headless mode for import, export, repair, and scheduled sync.
- Self-hosted web deployment guide (Flet web or a thin server) with auth/TLS
  guidance; Docker image if it does not add a mandatory server dependency.
- Signed desktop builds and documented packaging; Android build if the platform
  spike is green.
- Backup/restore, export/import, diagnostics bundle, and a repair tool.
- App lock, encryption at rest, auto-lock, and secrets in the OS keyring.
- Nextcloud compatibility matrix and setup guide (subpath, self-signed CA,
  app passwords).
- Community foundation: CONTRIBUTING, CODE_OF_CONDUCT, SECURITY.md, issue/PR
  templates, docs site, changelog, release process, funding.
- **Exit:** v1.0 for self-hosters on desktop + web + (if ready) Android; docs and
  migration from 0.1 verified; security review done.

### Phase 7 — Mainstream readiness (v1.x, ~8–12 weeks)

**Goal:** a non-technical person can use it daily.

- Onboarding wizard, sample budget, category templates, import from
  EveryDollar/YNAB/Actual CSV where feasible.
- Localization, locale formats, multi-currency, light/system theme, font scaling,
  semantics, keyboard navigation, contrast, RTL.
- Mobile UX pass (bottom sheets, gestures, responsive layouts), signed store
  builds, auto-update.
- Household sharing and multi-user budgets (if not already delivered).
- **Exit:** mainstream onboarding and accessibility checks pass; v1.x.

### Phase 8 — Bank sync and advanced integrations (post-v1.x, last)

**Goal:** optional conveniences that do not compromise the core.

- Optional bank sync via user-supplied providers (SimpleFIN/GoCardless first),
  behind a provider interface; secrets in the keyring; explicit consent; no
  default backend and no telemetry.
- Evaluate Plaid or similar only if there is a team and a sustainable business
  model for it.
- Investments, retirement projections, tax lots.
- API/plugins, custom reports, automation.
- Business/rental income, multi-currency FX.
- Optional local/opt-in AI assistant, only if privacy can be preserved.
- **Exit:** bank sync is opt-in, documented, and never required for core use.

## 10. Release map and rough effort

| Release | Theme | Effort (dev-weeks) |
|---|---|---|
| v0.2 | Trustworthy core | 3–5 |
| v0.3 | Local ledger | 8–12 |
| v0.4 | Budget + savings engine | 8–12 |
| v0.5 | Sync v2 | 8–14 |
| v0.6 | Reports and planning | 6–8 |
| v0.7 | Import and automation | 8–12 |
| v1.0 | Self-hoster release | 6–10 |
| **Total to v1.0** | | **~47–73 dev-weeks** |
| v1.x | Mainstream readiness | 8–12 |
| post-v1.x | Bank sync and advanced | 8–16+ |

That is roughly **12–17 months full-time** for one developer to v1.0, longer
part-time. Bank sync is deliberately outside that estimate.

## 11. Success metrics

- **Correctness:** zero P0 data-loss bugs; all migration fixtures pass; ledger
  invariants hold under property tests; sync fault-injection passes.
- **Fund accounting:** every recurring contribution produces exactly one budget
  impact and one transfer; one-off contributions produce zero budget impact;
  auto-post is idempotent across devices and restarts.
- **Quality:** ≥80% domain coverage, strict type checking, local checks green,
  UI smoke tests on every release.
- **Performance:** 10k transactions searchable in <100 ms; startup <1.5 s; sync
  of 1k ops <5 s on a typical connection.
- **Self-hosting:** a new user can go from download to synced Nextcloud budget
  using only the docs, without a database server.
- **Community:** issue triage <7 days, predictable releases, contributor count,
  docs coverage.
- **Privacy:** no telemetry by default; E2E verified; secrets in keyring; clear
  threat model.

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Scope creep / EveryDollar envy | Fixed wedge, explicit non-goals, phase gates, bank sync last. |
| Fund/budget double counting | One budget impact rule; linked budget-excluded transfers; tests for every movement type. |
| Auto-post duplicate or surprise transfers | Idempotency keys, catch-up rules, overdraft warnings, undo, visible register. |
| Sync complexity | Op log first, CRDT only if needed; fault injection; provider abstraction. |
| Flet limits (mobile, a11y, packaging) | Pure core + thin UI; early mobile/a11y spike; documented fallback plan. |
| Data loss during migration | Backups, dry-run, export, versioned migrations, fixtures from real data. |
| Security breach / leaked credentials | Keyring, E2E, dependency scanning, disclosure policy, threat model. |
| Bank aggregator cost/ToS/security | CSV first; user-supplied tokens; no server by default; defer to last. |
| Maintainer burnout | Scope discipline, governance, funding, contributor docs. |
| Trademark/legal (EveryDollar, Ramsey, Baby Steps, YNAB) | Generic language, no copied assets/content, legal review before marketing. |
| Currency/precision bugs | Integer minor units, currency code, property-based tests. |
| Nextcloud variability | Compatibility matrix, integration tests, actionable errors. |

## 13. Open questions

1. **Primary platform:** desktop, Android, or web first? Where do you personally
   use it most?
2. **License:** keep GPL-3.0, or move to AGPL-3.0 before accepting outside
   contributions?
3. **Sustainability:** donations, sponsorship, hosted sync, or pure volunteer?
4. **v1.0 definition:** what would make you recommend this to another
   self-hoster?
5. **Governance:** RFCs and a public roadmap, or a personal project with
   occasional contributors?

## 14. Recommended next steps

1. Start Phase 0 as the immediate workstream: data safety, migration foundation,
   backup/export, and quality gates.
2. Prototype the SQLite ledger and the fund/auto-post model against a copy of
   real data; verify every total reconciles and every contribution has exactly
   one budget impact.
3. Write a one-page v0.2/v0.3 scope and open issues; keep this roadmap as a
   living document.
4. Do not start bank sync, mainstream onboarding, or a UI rewrite before v1.0.
