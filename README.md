# Savings Funds

Savings Funds is a personal finance app for tracking savings goals and a simple
monthly budget. It is built with Python and Flet and runs as a desktop, mobile,
or web app.

## What it does

- Track savings funds with a target, current balance, optional target date, and
  recurring monthly contribution.
- Track monthly income and expenses, including each item's expected/budgeted
  amount and current received/spent amount.
- Automatically include each nonzero fund contribution as a budget expense.
  The generated expense follows the fund's contribution and is removed when the
  contribution becomes zero or the fund is deleted.
- Optionally synchronize the account balance, funds, and budget with Nextcloud.

The bottom navigation opens Budget on the left and Savings on the right. Fund
cards and budget items can be reordered within their list. Use the plus and
minus buttons to adjust current balances; editing a card lets you change its
target or other details.

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

## Local data and synchronization

The app stores data files in the project root:

| File | Contents |
| --- | --- |
| `balance.txt` | Current account balance |
| `funds.json` | Savings fund names, targets, balances, dates, and contributions |
| `budget.json` | Income and expense items and their budgeted/current amounts |
| `nextcloud_sync.json` | Nextcloud connection settings |

These files are ignored by Git. Keep a backup if you want to preserve local
data when moving or reinstalling the app. The Nextcloud settings file contains
the configured username and password, so it should remain private.

When configured, Nextcloud synchronization downloads the three data files on
startup and uploads local changes in the background. A missing remote file is
treated as empty: the app creates an empty local file when needed and continues
with the other downloads. An existing local file is preserved if its remote
copy is missing.

## Project structure

- `src/app.py` coordinates startup, persistence, page composition, and sync.
- `src/ui/savings.py` contains savings dialogs, cards, and the dashboard.
- `src/ui/budget.py` contains budget dialogs, cards, and the dashboard.
- `src/ui/settings.py` contains the header and Nextcloud settings screen.
- `src/ui/navigation.py` handles switching between pages.
- `src/ui/shared.py` contains dialogs shared across pages.
- `src/fund.py` and `src/budget.py` hold the savings and budget models.
- `src/data.py` reads and writes local data; `src/nextcloud.py` handles WebDAV.
- `src/colors.py` and `src/utils.py` contain shared presentation helpers.
- `tests/` contains model, persistence, synchronization, and UI tests.

## Tests

Run the offline model, persistence, and Nextcloud tests with:

```bash
uv run pytest tests/test_fund.py tests/test_budget.py tests/test_data.py tests/test_nextcloud.py
```

Run the complete suite, including Flet UI integration tests, with:

```bash
uv run flet test
```

The UI tests use temporary files and stub the Nextcloud server check. On Linux,
the Flet test host may need Flutter plus the GTK development prerequisites on
its first run.

## Build packages

Flet can build packages for Android, iOS, macOS, Linux, Windows, and the web.
For example, build a Linux package with:

```bash
uv run flet build linux -v
```

See the [Flet packaging guides](https://docs.flet.dev/publish/) for platform
requirements and signing instructions.
