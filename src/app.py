"""Application state, persistence, synchronization, and UI composition."""

import asyncio
import logging
from contextlib import suppress
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import flet as ft

import colors
from budget import (
    BudgetState,
    current_period,
    format_period,
    sync_recurring_fund_expenses,
)
from data import (
    DataFileError,
    UnsupportedSchemaError,
    backup_database,
    copy_plan_forward,
    export_database,
    latest_database_backup,
    load_budget,
    load_funds,
    migrate_legacy_json_data,
    reset_budget_period,
    restore_database,
    rollover_budget,
    save_budget,
    save_funds,
)
from fund import Fund
from ledger import Ledger, LedgerError
from nextcloud import (
    SyncConflictError,
    credential_storage_warning,
    load_nextcloud_sync_data_from_db,
    migrate_nextcloud_file_to_db,
    ping_nextcloud_server,
    save_nextcloud_sync_data_to_db,
    sync_data_to_nextcloud,
)
from paths import open_data_folder
from ui.budget import BudgetDashboard
from ui.navigation import AppPageNavigation
from ui.savings import Dashboard
from ui.settings import AppHeader, NextcloudConfigDialog, SettingsView
from ui.shared import AccountBalanceDialog, ConfirmDialog, MessageDialog
from ui.transactions import TransactionsDashboard

logger = logging.getLogger(__name__)

SYNC_DEBOUNCE_SECONDS = 0.5
NEXTCLOUD_SETUP_TIMEOUT_SECONDS = 600
PERIOD_CHECK_SECONDS = 60


def _next_period(period: str) -> str:
    year, month = (int(part) for part in period.split('-', 1))
    if month == 12:
        return f'{year + 1:04d}-01'
    return f'{year:04d}-{month + 1:02d}'


class SavingsFundsApp:
    """Application state, persistence, synchronization, and UI composition."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.ledger = Ledger()
        self.theme_mode = (
            self.ledger.get_setting(
                'theme_mode', self.ledger.get_meta('theme_mode', 'dark')
            )
            or 'dark'
        )
        self.transactions_dashboard = None
        self.nextcloud_sync_data = None
        self.funds: list[Fund] = []
        self.budget_state = BudgetState([], current_period())
        self.budget_categories = self.budget_state.categories
        self.account_balance: Decimal | None = None
        self.dashboard = None
        self.budget_dashboard = None
        self.navigation = None
        self.startup_errors: list[str] = []
        self.startup_notice: str | None = None
        self._sync_pending: dict[str, Path] = {}
        self._sync_failed: dict[str, Path] = {}
        self._sync_task = None
        self._period_task = None
        self._writes_blocked = False
        self._initialize_page()

    def _initialize_page(self):
        self.page.title = 'Savings Funds'
        self.page.theme_mode = (
            ft.ThemeMode.DARK if self.theme_mode == 'dark' else ft.ThemeMode.LIGHT
        )
        self.page.bgcolor = colors.BACKGROUND
        self.page.theme = colors.theme_for(self.theme_mode)
        self.page.scroll = None
        self.page.on_resize = lambda e: self._resize_dashboard()
        if isinstance(self.page, ft.Page):
            self.page.on_app_lifecycle_state_change = lambda e: (
                self._check_period_rollover()
            )

        self.nextcloud_dialog = NextcloudConfigDialog(
            self.page,
            self._on_nextcloud_config_saved,
            load_settings=lambda: load_nextcloud_sync_data_from_db(self.ledger),
            save_settings=lambda data: save_nextcloud_sync_data_to_db(
                data, self.ledger
            ),
        )
        self.header = AppHeader(self.show_settings)
        self.settings_view = SettingsView(
            self.page,
            self.show_dashboard,
            self.nextcloud_dialog,
            self._disable_nextcloud_sync,
            self._manual_sync,
            self._backup_data,
            self._export_data,
            self._restore_latest_backup,
            self._open_data_folder,
            self.theme_mode,
            self.set_theme_mode,
        )

        self.page.add(
            ft.SafeArea(
                content=self.header.control,
                avoid_intrusions_bottom=False,
                avoid_intrusions_left=False,
                avoid_intrusions_right=False,
            ),
            self.settings_view.control,
        )

    async def perform_nextcloud_sync(self):
        """Load Nextcloud settings from SQLite without blocking offline use.

        v0.4 stores connection settings and sync state in the single local
        database. Whole-file WebDAV synchronization is intentionally deferred
        to the v0.5 operation-log sync work; no remote file is read or written
        in this release.
        """
        try:
            migrate_nextcloud_file_to_db(self.ledger)
        except (DataFileError, OSError) as exc:
            self.startup_errors.append(str(exc))

        try:
            self.nextcloud_sync_data = load_nextcloud_sync_data_from_db(self.ledger)
        except (DataFileError, OSError) as exc:
            self.startup_errors.append(str(exc))
            self.nextcloud_sync_data = None

        warning = credential_storage_warning()
        if warning:
            self.startup_notice = (
                f'{self.startup_notice} {warning}' if self.startup_notice else warning
            )
        if self.nextcloud_sync_data:
            notice = (
                'Nextcloud settings are stored locally. Multi-device file sync '
                'will return in v0.5.'
            )
            self.startup_notice = (
                f'{self.startup_notice} {notice}' if self.startup_notice else notice
            )
            return

        if self.ledger.get_meta('nextcloud_prompted') == '1':
            return
        if not self.ledger.get_setting('nextcloud_config'):
            self.sync_dialog_closed = asyncio.Event()
            self.nextcloud_dialog.add(self.sync_dialog_closed)
            try:
                await asyncio.wait_for(
                    self.sync_dialog_closed.wait(),
                    timeout=NEXTCLOUD_SETUP_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                self.startup_notice = (
                    'Nextcloud setup timed out; continuing with local data.'
                )
                with suppress(Exception):
                    self.page.pop_dialog()
            finally:
                self.ledger.set_meta('nextcloud_prompted', '1')

    def _sync_file_in_background(self, file_path: Path):
        if not self.nextcloud_sync_data:
            return
        file_path = Path(file_path)
        self._sync_pending[file_path.name] = file_path
        # Retry files that failed on a previous attempt when the next change occurs.
        self._sync_pending.update(self._sync_failed)
        self._sync_failed.clear()
        if self._sync_task is None or self._sync_task.done():
            self._sync_task = self.page.run_task(self._sync_worker)

    async def _sync_worker(self):
        try:
            while self._sync_pending:
                await asyncio.sleep(SYNC_DEBOUNCE_SECONDS)
                pending = list(self._sync_pending.values())
                self._sync_pending.clear()
                for index, file_path in enumerate(pending):
                    if not self.nextcloud_sync_data:
                        return
                    if not file_path.exists():
                        continue
                    try:
                        await asyncio.to_thread(
                            sync_data_to_nextcloud, file_path, self.nextcloud_sync_data
                        )
                    except SyncConflictError as exc:
                        self._show_sync_error(str(exc))
                        # A conflict needs a fresh startup reconciliation. Keep
                        # the other files queued for the next local change.
                        self._defer_uploads(pending[index + 1 :])
                        return
                    except Exception as exc:
                        logger.exception('Nextcloud upload failed for %s', file_path)
                        self._show_sync_error(
                            f'Could not upload {file_path.name}: {exc}. '
                            'The change is saved locally and will be retried after '
                            'your next change.'
                        )
                        self._defer_uploads(pending[index:])
                        return
        finally:
            self._sync_task = None

    def _defer_uploads(self, file_paths):
        """Retain failed and untouched uploads for the next change."""
        for file_path in file_paths:
            self._sync_failed[file_path.name] = file_path
        self._sync_failed.update(self._sync_pending)
        self._sync_pending.clear()

    def _show_sync_error(self, message: str):
        self._show_snack(message, colors.RED)

    def _show_snack(self, message: str, bgcolor=None):
        self.page.show_dialog(ft.SnackBar(ft.Text(message), bgcolor=bgcolor))

    def _show_credential_warning(self):
        warning = credential_storage_warning()
        if warning:
            self._show_snack(warning, colors.RED)

    def _save_data(
        self,
        save_callable,
        label: str,
        *,
        allow_when_blocked: bool = False,
    ) -> bool | None:
        if self._writes_blocked and not allow_when_blocked:
            message = (
                'Writes are disabled because a data file was created by a newer '
                'version of Savings Funds. Update the app or restore a backup.'
            )
            if self.dashboard is None:
                if message not in self.startup_errors:
                    self.startup_errors.append(message)
            else:
                self._show_snack(message, colors.RED)
            return None
        try:
            return save_callable()
        except (OSError, DataFileError) as exc:
            logger.exception('Could not save %s', label)
            message = f'Could not save {label}: {exc}'
            if self.dashboard is None:
                self.startup_errors.append(message)
            else:
                self._show_snack(message, colors.RED)
            return None

    def _backup_data(self):
        try:
            destination = backup_database(self.ledger)
        except OSError as exc:
            self._show_snack(f'Could not create backup: {exc}', colors.RED)
            return
        self._show_snack(f'Backup created: {destination}')

    def _export_data(self):
        try:
            destination = export_database(ledger=self.ledger)
        except OSError as exc:
            self._show_snack(f'Could not export data: {exc}', colors.RED)
            return
        self._show_snack(f'Export created: {destination}')

    def _open_data_folder(self):
        try:
            open_data_folder()
        except OSError as exc:
            self._show_snack(f'Could not open data folder: {exc}', colors.RED)

    def _restore_latest_backup(self):
        try:
            source = latest_database_backup(self.ledger)
        except OSError as exc:
            self._show_snack(f'Could not find a backup: {exc}', colors.RED)
            return
        if source is None:
            self._show_snack('No database backup is available to restore.', colors.RED)
            return

        ConfirmDialog(
            self.page,
            'Restore latest backup?',
            f'Restore data from {source.name}? Current data will be backed up '
            'first. The app will reload the restored data.',
            lambda: self._perform_restore(source),
            confirm_label='Restore',
        ).open()

    def _perform_restore(self, source: Path):
        try:
            restore_database(source, self.ledger)
        except (OSError, ValueError, DataFileError) as exc:
            MessageDialog(
                self.page,
                'Restore failed',
                f'Could not restore the backup: {exc}. Current data was kept.',
            ).open()
            return
        try:
            self._reload_restored_data()
        except (OSError, ValueError, DataFileError) as exc:
            MessageDialog(
                self.page,
                'Restore complete',
                'The backup was restored, but the app could not reload it. '
                f'Restart Savings Funds to use the restored data. ({exc})',
            ).open()
            return
        self._show_snack(f'Restored data from {source.name}.')

    def _reload_restored_data(self):
        funds = load_funds(self.ledger)
        budget = load_budget(current_period(), ledger=self.ledger)

        self.funds[:] = funds
        self.budget_categories[:] = budget.categories
        # Keep the dashboard's list object and the state's list in sync.
        budget.categories = self.budget_categories
        self.budget_state = budget
        self.account_balance = (
            self.ledger.total_balance() if self.ledger.list_accounts() else None
        )
        self._writes_blocked = False

        if self.dashboard is not None:
            self.dashboard.refresh()
        if self.budget_dashboard is not None:
            self.budget_dashboard.period = budget.period
            self.budget_dashboard.refresh()
        self.page.update()

    def show_settings(self):
        if self.navigation is not None:
            self.navigation.set_visible(False)
        self.settings_view.show()

    def show_dashboard(self):
        self.settings_view.hide()
        if self.navigation is not None:
            self.navigation.set_visible(True)
        self.page.update()

    def _on_nextcloud_config_saved(self, sync_data):
        self.nextcloud_sync_data = sync_data
        if hasattr(self, 'settings_view'):
            self.settings_view.control.visible = True
        self.page.update()
        self._show_credential_warning()

    async def _manual_sync(self):
        if not self.nextcloud_sync_data:
            self._show_snack('Configure Nextcloud before syncing.', colors.RED)
            return
        success, message = await asyncio.to_thread(
            ping_nextcloud_server, self.nextcloud_sync_data
        )
        if success:
            self._show_snack(
                'Nextcloud connection OK. Multi-device data sync returns in v0.5.'
            )
        else:
            self._show_snack(f'Nextcloud sync failed: {message}', colors.RED)

    def _disable_nextcloud_sync(self):
        if (
            self._save_data(
                lambda: save_nextcloud_sync_data_to_db(None, self.ledger),
                'Nextcloud settings',
                allow_when_blocked=True,
            )
            is None
        ):
            return
        self.nextcloud_sync_data = None
        self._sync_pending.clear()
        self._sync_failed.clear()
        self._show_snack('Nextcloud synchronization is disabled.')
        self._show_credential_warning()

    def _record_load_error(self, exc: Exception):
        if isinstance(exc, UnsupportedSchemaError):
            self._writes_blocked = True
        self.startup_errors.append(str(exc))

    def load_account_balance_and_funds(self):
        funds_loaded = True
        budget_loaded = True
        try:
            migrate_legacy_json_data(self.ledger)
        except (DataFileError, OSError, LedgerError) as exc:
            self._record_load_error(exc)

        try:
            self.funds = load_funds(self.ledger)
        except (DataFileError, OSError, LedgerError) as exc:
            self.funds = []
            funds_loaded = False
            self._record_load_error(exc)

        try:
            self.budget_state = load_budget(current_period(), ledger=self.ledger)
            self.budget_categories = self.budget_state.categories
        except (DataFileError, OSError, LedgerError) as exc:
            self.budget_state = BudgetState([], current_period())
            self.budget_categories = self.budget_state.categories
            budget_loaded = False
            self._record_load_error(exc)

        if funds_loaded and budget_loaded:
            self._normalize_and_rollover_data()
        else:
            # Do not write incomplete state over data that failed to load.
            self.startup_notice = None

        balance_configured = self.ledger.get_setting(
            'account_balance_set'
        ) == '1' or bool(self.ledger.list_transactions())
        self.account_balance = (
            self.ledger.total_balance()
            if self.ledger.list_accounts() and balance_configured
            else None
        )
        self._auto_post_fund_contributions()

        if self.account_balance is None:
            dialog = AccountBalanceDialog(self.page, self.set_account_balance)
            dialog.add(self.initialize_dashboard, on_skip=self.initialize_dashboard)
        else:
            self.initialize_dashboard()

    def _rollover_budget_if_needed(self, today=None, *, notify: bool = False) -> bool:
        """Roll over with rollback so a failed save cannot strand the UI state."""
        if self._writes_blocked:
            return False
        previous_period = self.budget_state.period
        previous_categories = deepcopy(self.budget_state.categories)
        try:
            if not rollover_budget(self.budget_state, today, self.ledger):
                return False
        except (DataFileError, OSError, LedgerError) as exc:
            self.startup_errors.append(str(exc))
            return False

        if (
            self._save_data(
                lambda: save_budget(self.budget_state, self.ledger), 'budget plan'
            )
            is None
        ):
            self.budget_state.period = previous_period
            self.budget_state.categories[:] = previous_categories
            return False

        if notify:
            self.startup_notice = (
                f'Budget rolled over to {format_period(self.budget_state.period)}.'
            )
        return True

    def _normalize_and_rollover_data(self):
        self._rollover_budget_if_needed(notify=True)

        budget_changed = sync_recurring_fund_expenses(
            self.budget_categories, self.funds
        )
        if budget_changed:
            self._save_data(
                lambda: save_budget(self.budget_state, self.ledger), 'budget plan'
            )

        # Persist the current plan and fund definitions. The repositories skip
        # writes when nothing changed.
        self._save_data(lambda: save_funds(self.funds, self.ledger), 'funds')
        self._save_data(
            lambda: save_budget(self.budget_state, self.ledger), 'budget plan'
        )

    def set_account_balance(self, value):
        if self._writes_blocked:
            self._show_snack(
                'Writes are disabled because data was created by a newer '
                'version of Savings Funds.',
                colors.RED,
            )
            return
        try:
            self.ledger.set_total_balance(value)
        except LedgerError as exc:
            self._show_snack(f'Could not update the ledger: {exc}', colors.RED)
            return
        self.ledger.set_setting('account_balance_set', '1')
        self.account_balance = self.ledger.total_balance()
        self._refresh_ledger_view()

    def _on_ledger_changed(self):
        self.ledger.set_setting('account_balance_set', '1')
        self.account_balance = self.ledger.total_balance()
        self.funds[:] = self.ledger.list_funds()
        self.refresh_page()
        self._refresh_ledger_view()

    def _refresh_ledger_view(self):
        if self.transactions_dashboard is not None:
            self.transactions_dashboard.refresh()
            self.page.update()

    def set_theme_mode(self, mode):
        if mode not in {'dark', 'light'}:
            return
        self.theme_mode = mode
        self.ledger.set_setting('theme_mode', mode)
        self.ledger.set_meta('theme_mode', mode)
        self.page.theme_mode = (
            ft.ThemeMode.DARK if mode == 'dark' else ft.ThemeMode.LIGHT
        )
        self.page.theme = colors.theme_for(mode)
        self.page.bgcolor = colors.BACKGROUND
        self.page.update()

    def initialize_dashboard(self):
        current = current_period()
        if self.budget_state.period != current:
            self.budget_state = load_budget(current, ledger=self.ledger)
            self.budget_categories = self.budget_state.categories
        self.dashboard = Dashboard(
            self.page,
            self.funds,
            lambda: self.account_balance,
            self.set_account_balance,
            self._on_funds_changed,
            self._on_fund_contribution,
        )
        self.budget_dashboard = BudgetDashboard(
            self.page,
            self.budget_categories,
            self._on_budget_categories_changed,
            self.budget_state.period,
            self._reset_budget_month,
            self.funds,
            self._load_budget_period,
            self._copy_budget_plan,
        )
        self.transactions_dashboard = TransactionsDashboard(
            self.page, self.ledger, self._on_ledger_changed
        )
        self.navigation = AppPageNavigation(
            self.page,
            [
                self.dashboard.control,
                self.budget_dashboard.control,
                self.transactions_dashboard.control,
            ],
        )
        self.page.add(self.navigation.page_view)
        self.page.update()
        self.start_period_watcher()

        if self.startup_notice:
            self._show_snack(self.startup_notice)
        if self.startup_errors:
            MessageDialog(
                self.page,
                'Data problem',
                '\n\n'.join(self.startup_errors),
            ).open()

    def refresh_page(self):
        if self.dashboard is not None:
            self.dashboard.refresh()
        self.page.update()

    def start_period_watcher(self):
        """Check for a month change while the app stays open."""
        if self._period_task is not None or not isinstance(self.page, ft.Page):
            return
        self.page.on_disconnect = lambda e: self.stop_period_watcher()
        self._period_task = self.page.run_task(self._period_watcher)

    def stop_period_watcher(self):
        if self._period_task is None:
            return
        self._period_task.cancel()
        self._period_task = None

    async def _period_watcher(self):
        try:
            while True:
                await asyncio.sleep(PERIOD_CHECK_SECONDS)
                self._check_period_rollover()
        except asyncio.CancelledError:
            raise
        finally:
            self._period_task = None

    def _check_period_rollover(self):
        if self.dashboard is None:
            return False
        rolled = self._rollover_budget_if_needed()
        self._auto_post_fund_contributions()
        if not rolled:
            return False
        if self.budget_dashboard is not None:
            self.budget_dashboard.period = self.budget_state.period
            self.budget_dashboard.refresh()
        self.refresh_page()
        self._show_snack(
            f'Budget rolled over to {format_period(self.budget_state.period)}.'
        )
        return True

    def _auto_post_fund_contributions(self, *, notify: bool = False) -> list:
        if self._writes_blocked:
            return []
        try:
            posted = self.ledger.auto_post_fund_contributions(self.funds)
        except (LedgerError, OSError) as exc:
            self.startup_errors.append(f'Could not auto-post fund contributions: {exc}')
            return []
        if not posted:
            return []
        self.funds[:] = self.ledger.list_funds()
        self.account_balance = (
            self.ledger.total_balance() if self.ledger.list_accounts() else None
        )
        if notify and self.dashboard is not None:
            self._show_snack(
                f'Posted {len(posted)} scheduled fund contribution'
                f'{"s" if len(posted) != 1 else ""}.'
            )
        if self.dashboard is not None:
            self.dashboard.refresh()
        self._refresh_ledger_view()
        return posted

    def _on_funds_changed(self):
        changed = self._save_data(lambda: save_funds(self.funds, self.ledger), 'funds')
        if changed is None:
            return
        if sync_recurring_fund_expenses(self.budget_categories, self.funds):
            self._on_budget_categories_changed()
        self.refresh_page()

    def _on_fund_contribution(self, fund, amount):
        """Record a one-off, budget-excluded contribution from the savings card."""
        try:
            contribution = self.ledger.add_fund_contribution(
                fund,
                amount,
                kind='one_off',
                memo='One-off savings contribution',
                allow_negative=True,
            )
        except (LedgerError, OSError, ValueError) as exc:
            self._show_snack(f'Could not update the fund: {exc}', colors.RED)
            return
        if contribution is not None:
            self.funds[:] = self.ledger.list_funds()
        self.refresh_page()
        self._refresh_ledger_view()

    def _on_budget_categories_changed(self):
        self._save_data(
            lambda: save_budget(self.budget_state, self.ledger), 'budget plan'
        )
        if self.budget_dashboard is not None:
            self.budget_dashboard.refresh()
        self.page.update()

    def _load_budget_period(self, period: str):
        state = self.ledger.load_budget(period)
        if not self.ledger.has_budget_period(period):
            latest = self.ledger.load_budget()
            state = copy_plan_forward(latest, period, self.ledger)
            self._save_data(
                lambda: save_budget(state, self.ledger),
                'budget plan',
                allow_when_blocked=True,
            )
        self.budget_state = state
        self.budget_categories = state.categories
        sync_recurring_fund_expenses(self.budget_categories, self.funds)
        self._save_data(
            lambda: save_budget(self.budget_state, self.ledger), 'budget plan'
        )
        if self.budget_dashboard is not None:
            self.budget_dashboard.period = state.period
            self.budget_dashboard.categories = self.budget_categories
            self.budget_dashboard.dialog.categories = self.budget_categories
            self.budget_dashboard.refresh()
        self.page.update()

    def _copy_budget_plan(self):
        next_period = _next_period(self.budget_state.period)
        copied = copy_plan_forward(self.budget_state, next_period, self.ledger)
        self._save_data(
            lambda: save_budget(copied, self.ledger),
            'budget plan',
            allow_when_blocked=True,
        )
        self._load_budget_period(next_period)

    def _reset_budget_month(self):
        if self._writes_blocked:
            self._show_snack(
                'Writes are disabled because data was created by a newer '
                'version of Savings Funds.',
                colors.RED,
            )
            return
        previous_period = self.budget_state.period
        previous_categories = deepcopy(self.budget_state.categories)
        try:
            reset_budget_period(self.budget_state, ledger=self.ledger)
        except (DataFileError, OSError, LedgerError) as exc:
            self._show_snack(str(exc), colors.RED)
            return
        if (
            self._save_data(
                lambda: save_budget(self.budget_state, self.ledger), 'budget plan'
            )
            is None
        ):
            self.budget_state.period = previous_period
            self.budget_state.categories[:] = previous_categories
            return
        if self.budget_dashboard is not None:
            self.budget_dashboard.period = self.budget_state.period
            self.budget_dashboard.refresh()
        self.page.update()
        self._show_snack(f'Budget reset for {format_period(self.budget_state.period)}.')

    def _resize_dashboard(self):
        if self.dashboard is not None:
            self.dashboard.resize()
        if self.budget_dashboard is not None:
            self.budget_dashboard.resize()
        if self.dashboard is not None or self.budget_dashboard is not None:
            self.page.update()
