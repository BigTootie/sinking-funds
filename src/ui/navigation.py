"""Bottom navigation and page switching for the application."""

import flet as ft

import colors


class AppPageNavigation:
    """Switches between independently scrolling pages without a transition."""

    def __init__(self, page: ft.Page, pages: list[ft.Control]):
        self.page = page
        self.pages = pages
        self.selected_index = 0  # Page controls are ordered Savings, Budget.
        self.page_view = ft.Stack(
            controls=[
                ft.Container(content=pages[i], visible=(i == self.selected_index), expand=True,
                             key=f'app-page-{i}')
                for i in range(len(pages))
            ], expand=True, key='app-page-view',
        )
        self.navigation_bar = ft.NavigationBar(
            destinations=[
                ft.NavigationBarDestination(
                    icon=ft.Icons.PIE_CHART_OUTLINE,
                    selected_icon=ft.Icons.PIE_CHART,
                    label='Budget',
                    key='nav-budget',
                ),
                ft.NavigationBarDestination(
                    icon=ft.Icons.SAVINGS_OUTLINED,
                    selected_icon=ft.Icons.SAVINGS,
                    label='Savings',
                    key='nav-savings',
                ),
            ],
            selected_index=1,
            bgcolor=colors.SURFACE,
            indicator_color=colors.BLUE,
            on_change=self._on_navigation_change,
        )
        self.page.navigation_bar = self.navigation_bar

    def _on_navigation_change(self, e):
        # Bottom bar order is Budget, Savings; app content order remains Savings, Budget.
        self.selected_index = 1 if e.control.selected_index == 0 else 0
        for i, container in enumerate(self.page_view.controls):
            container.visible = i == self.selected_index
        self.page.update()

    def set_visible(self, visible: bool):
        self.page_view.visible = visible
        self.navigation_bar.visible = visible
