"""Helpers for driving the app's real Flet controls without a Flutter host."""

import inspect
from types import SimpleNamespace

import flet as ft


class FakePage:
    """Minimal page surface used by the app and its UI controls in tests."""

    def __init__(self, width=1280, height=1400):
        self.width = width
        self.height = height
        self.title = None
        self.theme_mode = None
        self.bgcolor = None
        self.theme = None
        self.scroll = None
        self.navigation_bar = None
        self.controls = []
        self.dialogs = []
        self.update_count = 0

    def add(self, *controls):
        self.controls.extend(controls)

    def update(self):
        self.update_count += 1

    def show_dialog(self, control):
        self.dialogs.append(control)

    def pop_dialog(self):
        if self.dialogs:
            self.dialogs.pop()


def _walk(value, seen):
    if isinstance(value, ft.Control):
        if id(value) in seen:
            return
        seen.add(id(value))
        yield value
        for child in value.__dict__.values():
            yield from _walk(child, seen)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk(child, seen)
    elif isinstance(value, (list, tuple, set)):
        for child in value:
            yield from _walk(child, seen)


def all_controls(page):
    """Yield every control reachable from the page, dialogs, and navigation."""
    seen = set()
    yield from _walk(page.controls, seen)
    yield from _walk(page.dialogs, seen)
    yield from _walk(page.navigation_bar, seen)


def find_by_key(page, key, count=1):
    """Find controls by key and assert the expected number is present."""
    controls = [
        control
        for control in all_controls(page)
        if getattr(control, 'key', None) == key
    ]
    assert len(controls) == count, (
        f'Expected {key!r} to match {count} controls, found {len(controls)}'
    )
    return controls[0] if count == 1 else controls


def find_by_text(page, value, containing=False):
    """Return visible Text controls whose value matches the expected text."""
    matches = []
    for control in all_controls(page):
        if not isinstance(control, ft.Text) or not isinstance(control.value, str):
            continue
        if containing:
            if value in control.value:
                matches.append(control)
        elif control.value == value:
            matches.append(control)
    return matches


async def click(page, key):
    """Invoke a control's click handler, awaiting async handlers."""
    control = find_by_key(page, key)
    handler = getattr(control, 'on_click', None)
    assert handler is not None, f'{key!r} has no click handler'
    result = handler(SimpleNamespace(control=control))
    if inspect.isawaitable(result):
        await result
    return control


async def enter(page, key, value):
    """Set a text field's value directly."""
    control = find_by_key(page, key)
    assert isinstance(control, ft.TextField), f'{key!r} is not a text field'
    control.value = value
    return control


def navigate(page, app, bar_index):
    """Switch pages using the bottom navigation bar's selected index."""
    bar = app.navigation.navigation_bar
    bar.on_change(SimpleNamespace(control=SimpleNamespace(selected_index=bar_index)))
    page.update()


def visible_page(app, index):
    """Return whether the app page at *index* is currently visible."""
    return app.navigation.page_view.controls[index].visible


def fund_key(app, name):
    fund = next(fund for fund in app.funds if fund.name == name)
    return f'fund-card-{fund.id}'


def budget_key(app, name):
    category = next(
        category for category in app.budget_categories if category.name == name
    )
    return f'budget-category-{category.category_id}'


def budget_action_key(app, name, action):
    category = next(
        category for category in app.budget_categories if category.name == name
    )
    return f'budget-{action}-{category.category_id}'
