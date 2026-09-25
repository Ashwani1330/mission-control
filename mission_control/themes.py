"""Colour themes. `t` cycles through them; the choice is remembered in settings."""

from __future__ import annotations

from textual.theme import Theme

THEMES = [
    Theme(name="mc-dark", dark=True, primary="#E8663D", accent="#E8663D", secondary="#8A8F98",
          foreground="#D4D4D4", background="#0B0B0C", surface="#111113", panel="#1C1C1F",
          success="#7FB77E", warning="#E0B04B", error="#E0605B"),
    Theme(name="mc-dusk", dark=True, primary="#6CB6D9", accent="#6CB6D9", secondary="#9AA5B1",
          foreground="#CDD6E0", background="#161A21", surface="#1B2029", panel="#262C37",
          success="#8BC48A", warning="#E3C07A", error="#E07A7A"),
    Theme(name="mc-light", dark=False, primary="#C2410C", accent="#C2410C", secondary="#57534E",
          foreground="#1C1917", background="#FAFAF9", surface="#F2F1EF", panel="#E3E1DE",
          success="#15803D", warning="#A16207", error="#B91C1C"),
]
BY_NAME = {theme.name: theme for theme in THEMES}
DEFAULT = THEMES[0].name
