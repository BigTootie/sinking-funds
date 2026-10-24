import asyncio

import flet as ft

from app import SavingsFundsApp


async def main(page: ft.Page):
    app = SavingsFundsApp(page)
    await app.perform_nextcloud_sync()
    app.load_account_balance_and_funds()


if __name__ == '__main__':
    ft.run(main)
