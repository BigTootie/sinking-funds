import flet as ft

import colors
from fund import Fund


def _money_format(value):
    return f'${value:,.2f}'


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

