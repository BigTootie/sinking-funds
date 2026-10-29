"""Semantic colors and light/dark theme palettes."""

import flet as ft

BACKGROUND = ft.Colors.SURFACE
SURFACE = ft.Colors.SURFACE_CONTAINER_LOW
SURFACE_HOVER = ft.Colors.SURFACE_CONTAINER_HIGH
BORDER = ft.Colors.OUTLINE_VARIANT

TEXT_PRIMARY = ft.Colors.ON_SURFACE
TEXT_SECONDARY = ft.Colors.ON_SURFACE_VARIANT

GREEN = ft.Colors.TERTIARY
BLUE = ft.Colors.PRIMARY
ORANGE = ft.Colors.SECONDARY
RED = ft.Colors.ERROR


def theme_for(mode: str) -> ft.Theme:
    """Return the blue-accented light or dark theme."""
    dark = mode == 'dark'
    return ft.Theme(
        color_scheme=ft.ColorScheme(
            primary='#60A5FA' if dark else '#2563EB',
            on_primary='#0B1220' if dark else '#FFFFFF',
            secondary='#FB923C' if dark else '#C2410C',
            on_secondary='#0B1220' if dark else '#FFFFFF',
            tertiary='#4ADE80' if dark else '#15803D',
            on_tertiary='#0B1220' if dark else '#FFFFFF',
            error='#F87171' if dark else '#B91C1C',
            on_error='#0B1220' if dark else '#FFFFFF',
            surface='#0B1220' if dark else '#F4F7FC',
            on_surface='#F5F5F5' if dark else '#172033',
            on_surface_variant='#A3A3A3' if dark else '#5B6475',
            outline_variant='#333333' if dark else '#D8DEE9',
            surface_container_low='#121212' if dark else '#FFFFFF',
            surface_container='#181818' if dark else '#EDF2F9',
            surface_container_high='#292929' if dark else '#E2E9F3',
        )
    )
