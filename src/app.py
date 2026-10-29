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
    ACCOUNT_BALANCE_FILE,
    BUDGET_FILE,
    BUDGET_HISTORY_FILE,
    FUNDS_FILE,
    DataFileError,
    UnsupportedSchemaError,
    backup_all_files,
    export_data,
    latest_full_backup,
    load_balance_from_txt,
    load_budget_from_json,
    load_funds_from_json,
    reset_budget_period,
    restore_backup,
    rollover_budget,
    save_balance_to_txt,
    save_budget_to_json,
    save_funds_to_json,
)
from fund import Fund
from ledger import Ledger, LedgerError
from nextcloud import (
    NEXTCLOUD_DATA_FILE,
    SyncConflictError,
    credential_storage_warning,
    load_nextcloud_sync_data,
    save_nextcloud_sync_data,
    sync_data_from_nextcloud,
    sync_data_to_nextcloud,
)
from paths import open_data_folder
from ui.budget import BudgetDashboard
from ui.navigation import AppPageNavigation
from ui.savings import Dashboard
from ui.settings import AppHeader, NextcloudConfigDialog, SettingsView
from ui.shared import AccountBalanceDialog, ConfirmDialog, LoadingDialog, MessageDialog
from ui.transactions import TransactionsDashboard

logger = logging.getLogger(__name__)

SYNC_DEBOUNCE_SECONDS = 0.5
NEXTCLOUD_SETUP_TIMEOUT_SECONDS = 600
PERIOD_CHECK_SECONDS = 60


class SavingsFundsApp:
    """Application state, persistence, synchronization, and UI composition."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.ledger = Ledger()
        self.theme_mode = self.ledger.get_meta('theme_mode', 'dark') or 'dark'
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
        self.page.on_resized = lambda e: self._resize_dashboard()
        if isinstance(self.page, ft.Page):
            self.page.on_app_lifecycle_state_change = lambda e: (
                self._check_period_rollover()
            )

        self.nextcloud_dialog = NextcloudConfigDialog(
            self.page, self._on_nextcloud_config_saved
        )
        self.header = AppHeader(self.show_settings)
        self.settings_view = SettingsView(
            self.page,
            self.show_dashboard,
            self.nextcloud_dialog,
            self._disable_nextcloud_sync,
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
        """Synchronize at startup without preventing offline use."""
        if not NEXTCLOUD_DATA_FILE.exists():
            self.sync_dialog_closed = asyncio.Event()
            self.nextcloud_dialog.add(self.sync_dialog_closed)
            try:
                await asyncio.wait_for(
                    self.sync_dialog_closed.wait(),
                    timeout=NEXTCLOUD_SETUP_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                # Never let optional setup block offline access to local data.
                self.startup_notice = (
                    'Nextcloud setup timed out; continuing with local data.'
                )
                with suppress(Exception):
                    self.page.pop_dialog()

        try:
            self.nextcloud_sync_data = load_nextcloud_sync_data()
        except (DataFileError, OSError) as exc:
            self.startup_errors.append(str(exc))
            self.nextcloud_sync_data = None
            return

        warning = credential_storage_warning()
        if warning:
            self.startup_notice = (
                f'{self.startup_notice} {warning}' if self.startup_notice else warning
            )
        if not self.nextcloud_sync_data:
            return

        loading_dialog = LoadingDialog(self.page, 'Syncing with Nextcloud...')
        loading_dialog.open()
        try:
            result = await asyncio.to_thread(
                sync_data_from_nextcloud, self.nextcloud_sync_data
            )
            for file_path in result.uploads:
                self._sync_file_in_background(file_path)
            for invalid_path in result.invalid_locals:
                original_name = invalid_path.name.split('.corrupt-', 1)[0]
                self.startup_errors.append(
                    f'Local {original_name} could not be read. The damaged copy was '
                    f'saved as {invalid_path.name}.'
                )
            for conflict_path in result.conflicts:
                self.startup_errors.append(
                    f'Nextcloud had a different copy of {conflict_path.name.rsplit(".remote-", 1)[0]}. '
                    f'The remote copy was saved as {conflict_path.name}; local data was kept.'
                )
        except Exception as exc:
            logger.exception('Startup Nextcloud sync failed')
            self.startup_errors.append(
                f'Nextcloud sync failed: {exc}. Local data is being used.'
            )
        finally:
            self.page.pop_dialog()

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
            destination = backup_all_files()
        except OSError as exc:
            self._show_snack(f'Could not create backup: {exc}', colors.RED)
            return
        self._show_snack(f'Backup created: {destination}')

    def _export_data(self):
        try:
            destination = export_data()
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
            source = latest_full_backup()
        except OSError as exc:
            self._show_snack(f'Could not find a backup: {exc}', colors.RED)
            return
        if source is None:
            self._show_snack('No full backup is available to restore.', colors.RED)
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
            restored = restore_backup(source)
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
        for path in restored:
            self._sync_file_in_background(path)
        self._show_snack(f'Restored data from {source.name}.')

    def _reload_restored_data(self):
        funds = load_funds_from_json()
        budget = load_budget_from_json(funds)
        balance = load_balance_from_txt()

        self.funds[:] = funds
        self.budget_categories[:] = budget.categories
        # Keep the dashboard's list object and the state's list in sync.
        budget.categories = self.budget_categories
        self.budget_state = budget
        self.account_balance = balance
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

    def _disable_nextcloud_sync(self):
        if (
            self._save_data(
                lambda: save_nextcloud_sync_data(None),
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
            self.funds = load_funds_from_json()
        except (DataFileError, OSError) as exc:
            self.funds = []
            funds_loaded = False
            self._record_load_error(exc)

        try:
            self.budget_state = load_budget_from_json(
                self.funds if funds_loaded else None
            )
            self.budget_categories = self.budget_state.categories
        except (DataFileError, OSError) as exc:
            self.budget_state = BudgetState([], current_period())
            self.budget_categories = self.budget_state.categories
            budget_loaded = False
            self._record_load_error(exc)

        try:
            self.account_balance = load_balance_from_txt()
        except (DataFileError, OSError) as exc:
            self.account_balance = None
            self._record_load_error(exc)

        if funds_loaded and budget_loaded:
            self._normalize_and_rollover_data()
        else:
            # Do not write incomplete state over files that failed to load.
            self.startup_notice = None

        had_balance = self.account_balance is not None
        try:
            self.ledger.seed_legacy(
                self.account_balance,
                self.funds,
                self.budget_categories,
                self.budget_state.period,
            )
            if had_balance:
                self.account_balance = self.ledger.total_balance()
        except (LedgerError, OSError) as exc:
            self.startup_errors.append(f'Could not initialize the local ledger: {exc}')

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
            if not rollover_budget(self.budget_state, today):
                return False
        except (DataFileError, OSError) as exc:
            self.startup_errors.append(str(exc))
            return False

        if (
            self._save_data(
                lambda: save_budget_to_json(self.budget_state), 'budget.json'
            )
            is None
        ):
            self.budget_state.period = previous_period
            self.budget_state.categories[:] = previous_categories
            return False

        self._sync_file_in_background(BUDGET_FILE)
        self._sync_file_in_background(BUDGET_HISTORY_FILE)
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
        if budget_changed and self._save_data(
            lambda: save_budget_to_json(self.budget_state), 'budget.json'
        ):
            self._sync_file_in_background(BUDGET_FILE)

        # Persist generated IDs and the versioned schema.  Unchanged files are
        # left alone by the atomic writer.
        if self._save_data(lambda: save_funds_to_json(self.funds), 'funds.json'):
            self._sync_file_in_background(FUNDS_FILE)
        if self._save_data(
            lambda: save_budget_to_json(self.budget_state), 'budget.json'
        ):
            self._sync_file_in_background(BUDGET_FILE)

    def set_account_balance(self, value):
        try:
            self.ledger.set_total_balance(value)
        except LedgerError as exc:
            self._show_snack(f'Could not update the ledger: {exc}', colors.RED)
            return
        self.account_balance = self.ledger.total_balance()
        if self._save_data(
            lambda: save_balance_to_txt(self.account_balance), 'balance.txt'
        ):
            self._sync_file_in_background(ACCOUNT_BALANCE_FILE)
        self._refresh_ledger_view()

    def _on_ledger_changed(self):
        self.account_balance = self.ledger.total_balance()
        if self._save_data(
            lambda: save_balance_to_txt(self.account_balance), 'balance.txt'
        ):
            self._sync_file_in_background(ACCOUNT_BALANCE_FILE)
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
        self.ledger.set_meta('theme_mode', mode)
        self.page.theme_mode = (
            ft.ThemeMode.DARK if mode == 'dark' else ft.ThemeMode.LIGHT
        )
        self.page.theme = colors.theme_for(mode)
        self.page.bgcolor = colors.BACKGROUND
        self.page.update()

    def initialize_dashboard(self):
        self.dashboard = Dashboard(
            self.page,
            self.funds,
            lambda: self.account_balance,
            self.set_account_balance,
            self._on_funds_changed,
        )
        self.budget_dashboard = BudgetDashboard(
            self.page,
            self.budget_categories,
            self._on_budget_categories_changed,
            self.budget_state.period,
            self._reset_budget_month,
            self.funds,
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
        if not self._rollover_budget_if_needed():
            return False
        if self.budget_dashboard is not None:
            self.budget_dashboard.period = self.budget_state.period
            self.budget_dashboard.refresh()
        self.refresh_page()
        self._show_snack(
            f'Budget rolled over to {format_period(self.budget_state.period)}.'
        )
        return True

    def _on_funds_changed(self):
        changed = self._save_data(lambda: save_funds_to_json(self.funds), 'funds.json')
        if changed is None:
            return
        if changed:
            self._sync_file_in_background(FUNDS_FILE)
        if sync_recurring_fund_expenses(self.budget_categories, self.funds):
            self._on_budget_categories_changed()
        self.refresh_page()

    def _on_budget_categories_changed(self):
        changed = self._save_data(
            lambda: save_budget_to_json(self.budget_state), 'budget.json'
        )
        if changed:
            self._sync_file_in_background(BUDGET_FILE)
        if self.budget_dashboard is not None:
            self.budget_dashboard.refresh()
        self.page.update()

    def _reset_budget_month(self):
        if self._writes_blocked:
            self._show_snack(
                'Writes are disabled because a data file was created by a newer '
                'version of Savings Funds.',
                colors.RED,
            )
            return
        previous_period = self.budget_state.period
        previous_categories = deepcopy(self.budget_state.categories)
        try:
            reset_budget_period(self.budget_state)
        except (DataFileError, OSError) as exc:
            self._show_snack(str(exc), colors.RED)
            return
        if (
            self._save_data(
                lambda: save_budget_to_json(self.budget_state), 'budget.json'
            )
            is None
        ):
            self.budget_state.period = previous_period
            self.budget_state.categories[:] = previous_categories
            return
        self._sync_file_in_background(BUDGET_FILE)
        self._sync_file_in_background(BUDGET_HISTORY_FILE)
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
