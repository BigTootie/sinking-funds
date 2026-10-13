import flet as ft

import colors
from fund import Fund


def _money_format(value):
    return f'${value:,.2f}'


BASIC_PROGRESS_BAR = ft.ProgressBar(value=0, color=colors.BLUE, bgcolor=colors.BORDER,
                              height=8, border_radius=10)


PAGE_HEADER = ft.Container(
    content=ft.Row(
        [
            ft.Container(content=ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, size=23),
                         bgcolor=colors.BLUE, border_radius=12, padding=10),
            ft.Column(
                [
                    ft.Text('Savings Funds', size=20, weight=ft.FontWeight.BOLD),
                    ft.Text('Give every dollar a purpose.', size=12),
                ],
                spacing=2,
                expand=True,
            ),
            ft.IconButton(icon=ft.Icons.SETTINGS_OUTLINED, tooltip='Settings',
                          icon_color=colors.TEXT_SECONDARY),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    ),
    padding=20,
    border=ft.Border.only(bottom=ft.BorderSide(1, '#E9EDF2')))


TOTAL_SAVINGS_TEXT = ft.Text(size=32, weight=ft.FontWeight.BOLD)
TOTAL_ALLOCATED_TEXT = ft.Text(size=13, color=colors.TEXT_SECONDARY)
TOTAL_UNALLOCATED_TEXT = ft.Text(size=12, color=colors.TEXT_SECONDARY)

TOTAL_SAVINGS_SUMMARY = ft.Container(
    content=ft.Column(
        [
            ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text('TOTAL SAVINGS', size=11, weight=ft.FontWeight.BOLD),
                            TOTAL_SAVINGS_TEXT,
                        ],
                        spacing=6,
                        expand=True,
                    ),
                    ft.Container(content=ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, size=26),
                                 border_radius=14, padding=14),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            TOTAL_ALLOCATED_TEXT,
            BASIC_PROGRESS_BAR,
            TOTAL_UNALLOCATED_TEXT,
        ],
        spacing=12,
    ),
    border=ft.Border.all(1, '#E9EDF2'),
    border_radius=18,
    padding=22,
)

def refresh_summary(total_savings: float, total_allocated: float):
    TOTAL_SAVINGS_TEXT.value = _money_format(total_savings)
    TOTAL_ALLOCATED_TEXT.value = \
        f'{_money_format(total_allocated)} allocated of {TOTAL_SAVINGS_TEXT.value}'
    TOTAL_UNALLOCATED_TEXT.value = f'{_money_format(total_savings - total_allocated)} unallocated'


def create_fund_card(fund: Fund) -> ft.Container:
    icon_box = ft.Container(content=ft.Icon(ft.Icons.SHIELD, size=24), bgcolor=colors.SURFACE,
                            border_radius=12, padding=11)

    details = ft.Column([ft.Text(fund.name, size=15, weight=ft.FontWeight.W_600),
                         ft.Text(f'Target {_money_format(fund.target)}' if fund.target > 0 \
                                                                        else 'No target set',
                                 size=12)
                        ], spacing=4, expand=True)

    amounts = ft.Column([ft.Text(_money_format(fund.balance), size=16, weight=ft.FontWeight.BOLD),
                         ft.Text(f'{fund.percent_funded:.1f}% funded' if fund.target > 0 \
                                                                      else 'No target',
                                 size=12),
                        ], spacing=4, horizontal_alignment=ft.CrossAxisAlignment.END)

    return ft.Container(
        content=ft.Column(
            [ft.Row([icon_box, details, amounts], spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.ProgressBar(value=min(max(fund.percent_funded / 100, 0), 1), height=6,
                           border_radius=10, color=colors.BLUE, bgcolor=colors.BORDER),
            ], spacing=14),
        border=ft.Border.all(1, colors.BORDER),
        border_radius=16,
        padding=16,
    )
