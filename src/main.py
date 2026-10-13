import flet as ft

from fund import Fund
from data import load_funds_from_json

FUNDS_FILE = 'funds.json'
ACCOUNT_BALANCE = 25000


# Dark theme colors
BACKGROUND = '#121212'
SURFACE = '#1E1E1E'
SURFACE_HOVER = '#292929'
BORDER = '#333333'

TEXT_PRIMARY = '#F5F5F5'
TEXT_SECONDARY = '#A3A3A3'

GREEN = '#4ADE80'
BLUE = '#60A5FA'
ORANGE = '#FB923C'
RED = '#F87171'


def main(page: ft.Page):

    funds = load_funds_from_json(FUNDS_FILE)

    page.title = 'Savings Funds'
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BACKGROUND
    page.theme = ft.Theme(color_scheme=ft.ColorScheme(primary=BLUE, surface=SURFACE))
    page.scroll = ft.ScrollMode.AUTO

    def money(value):
        return f'${value:,.2f}'

    def allocated():
        return sum(b.balance for b in funds)

    # ---------- Dashboard components ----------

    total_text = ft.Text(
        size=32,
        weight=ft.FontWeight.BOLD,
    )
    allocation_text = ft.Text(size=13, color='#64748B')
    unallocated_text = ft.Text(size=12, color='#64748B')

    allocation_progress = ft.ProgressBar(
        value=0,
        color=BLUE,
        bgcolor=BORDER,
        height=8,
        border_radius=10,
    )

    fund_list = ft.Column(spacing=12)

    def fund_card(fund):
        icon_box = ft.Container(
            content=ft.Icon(
                ft.Icons.SHIELD,
                size=24,
            ),
            bgcolor=SURFACE,
            border_radius=12,
            padding=11,
        )

        details = ft.Column(
            [
                ft.Text(
                    fund.name,
                    size=15,
                    weight=ft.FontWeight.W_600,
                ),
                ft.Text(
                    f'Target {money(fund.target)}'
                    if fund.target > 0
                    else 'No target set',
                    size=12,
                ),
            ],
            spacing=4,
            expand=True,
        )

        amounts = ft.Column(
            [
                ft.Text(
                    money(fund.balance),
                    size=16,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    f'{fund.percent_funded:.1f}% funded' if fund.target > 0 else 'No target',
                    size=12,
                ),
            ],
            spacing=4,
            horizontal_alignment=ft.CrossAxisAlignment.END,
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [icon_box, details, amounts],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.ProgressBar(
                        value=min(max(fund.percent_funded / 100, 0), 1),
                        height=6,
                        border_radius=10,
                        color=BLUE,
                        bgcolor=BORDER,
                    ),
                ],
                spacing=14,
            ),
            border=ft.Border.all(1, '#E9EDF2'),
            border_radius=16,
            padding=16,
        )

    def refresh():
        total_text.value = money(ACCOUNT_BALANCE)
        allocation_text.value = (
            f'{money(allocated())} allocated of '
            f'{money(ACCOUNT_BALANCE)}'
        )
        unallocated_text.value = (
            f'{money(ACCOUNT_BALANCE - allocated())} unallocated'
        )

        allocation_progress.value = (
            min(allocated() / ACCOUNT_BALANCE, 1)
            if ACCOUNT_BALANCE > 0
            else 0
        )

        fund_list.controls = [fund_card(b) for b in funds]
        page.update()

    # ---------- Dialog helpers ----------

    def close_dialog(dialog):
        page.pop_dialog()

    def open_add_fund(e):
        name_input = ft.TextField(label='Fund name')
        target_input = ft.TextField(
            label='Savings target ($)',
            value='0',
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        error = ft.Text(color='#DC2626', size=12)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text('Add a fund'),
            content=ft.Column(
                [name_input, target_input, error],
                tight=True,
                width=320,
            ),
        )

        def save_fund(e):
            name = (name_input.value or '').strip()

            try:
                target = float(target_input.value or '0')
                if target < 0:
                    raise ValueError
            except ValueError:
                error.value = 'Enter a valid target amount.'
                page.update()
                return

            if not name:
                error.value = 'Enter a fund name.'
                page.update()
                return

            funds.append(Fund(name, target, 0.0))

            close_dialog(dialog)
            refresh()

        dialog.actions = [
            ft.TextButton(
                'Cancel',
                on_click=lambda e: close_dialog(dialog),
            ),
            ft.FilledButton(
                'Add fund',
                on_click=save_fund,
            ),
        ]

        page.show_dialog(dialog)

    def open_move_money(e):
        if len(funds) < 2:
            return

        source = ft.Dropdown(
            label='Move money from',
            options=[
                ft.dropdown.Option(b.name)
                for b in funds
            ],
            value=funds[0].name,
        )

        destination = ft.Dropdown(
            label='Move money to',
            options=[
                ft.dropdown.Option(b.name)
                for b in funds
            ],
            value=funds[1].name,
        )

        amount = ft.TextField(
            label='Amount ($)',
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        error = ft.Text(color='#DC2626', size=12)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text('Move money'),
            content=ft.Column(
                [source, destination, amount, error],
                tight=True,
                width=320,
            ),
        )

        def transfer(e):
            try:
                value = float(amount.value or '0')
                if value <= 0:
                    raise ValueError
            except ValueError:
                error.value = 'Enter an amount greater than zero.'
                page.update()
                return

            src = next(
                b for b in funds if b.name == source.value
            )
            dst = next(
                b for b in funds if b.name == destination.value
            )

            if src is dst:
                error.value = 'Choose two different funds.'
                page.update()
                return

            if value > src.balance:
                error.value = 'Insufficient funds in that fund.'
                page.update()
                return

            src.balance -= value
            dst.balance += value

            close_dialog(dialog)
            refresh()

        dialog.actions = [
            ft.TextButton(
                'Cancel',
                on_click=lambda e: close_dialog(dialog),
            ),
            ft.FilledButton(
                'Transfer',
                on_click=transfer,
            ),
        ]

        page.show_dialog(dialog)

    # ---------- Header ----------

    header = ft.Container(
        content=ft.Row(
            [
                ft.Container(
                    content=ft.Icon(
                        ft.Icons.ACCOUNT_BALANCE_WALLET,
                        size=23,
                    ),
                    bgcolor=BLUE,
                    border_radius=12,
                    padding=10,
                ),
                ft.Column(
                    [
                        ft.Text(
                            'Savings Funds',
                            size=20,
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Text(
                            'Give every dollar a purpose.',
                            size=12,
                        ),
                    ],
                    spacing=2,
                    expand=True,
                ),
                ft.IconButton(
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    tooltip='Settings',
                    icon_color='#64748B',
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=20,
        border=ft.Border.only(
            bottom=ft.BorderSide(1, '#E9EDF2')
        ),
    )

    # ---------- Savings summary ----------

    summary = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text(
                                    'TOTAL SAVINGS',
                                    size=11,
                                    weight=ft.FontWeight.BOLD,
                                ),
                                total_text,
                            ],
                            spacing=6,
                            expand=True,
                        ),
                        ft.Container(
                            content=ft.Icon(
                                ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED,
                                size=26,
                            ),
                            border_radius=14,
                            padding=14,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                allocation_text,
                allocation_progress,
                unallocated_text,
            ],
            spacing=12,
        ),
        border=ft.Border.all(1, '#E9EDF2'),
        border_radius=18,
        padding=22,
    )

    heading = ft.Row(
        [
            ft.Column(
                [
                    ft.Text(
                        'Your funds',
                        size=19,
                        weight=ft.FontWeight.BOLD,
                    ),
                    ft.Text(
                        'Track progress toward what matters.',
                        size=12,
                    ),
                ],
                spacing=4,
                expand=True,
            ),
            ft.FilledButton(
                'Add fund',
                icon=ft.Icons.ADD,
                on_click=open_add_fund,
            ),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    actions = ft.Row(
        [
            ft.OutlinedButton(
                'Add fund',
                icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                on_click=open_add_fund,
                expand=True,
            ),
            ft.OutlinedButton(
                'Move money',
                icon=ft.Icons.SWAP_HORIZ,
                on_click=open_move_money,
                expand=True,
            ),
        ],
        spacing=12,
    )

    dashboard = ft.Container(
        content=ft.Column(
            [
                summary,
                heading,
                fund_list,
                actions,
                ft.Text(
                    'Demo data only · Not saved after restarting',
                    size=11,
                    color='#94A3B8',
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            spacing=18,
        ),
        width=760,
        padding=24,
    )

    page.add(
        header,
        ft.Row(
            [dashboard],
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.START,
        ),
    )

    refresh()


if __name__ == '__main__':
    ft.run(main)
