import flet as ft


async def main(page: ft.Page):
    # Resolve and migrate durable storage before importing modules that bind
    # data file paths at import time.
    import paths

    paths.initialize_data_storage()
    from app import SavingsFundsApp

    app = SavingsFundsApp(page)
    await app.perform_nextcloud_sync()
    app.load_account_balance_and_funds()


if __name__ == '__main__':
    ft.run(main)
