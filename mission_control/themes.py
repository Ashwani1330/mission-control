"""Colour themes. `t` cycles through them; the choice is remembered in settings.

Each theme has one accent (focus, brand, progress) and one secondary colour (tool names),
on backgrounds that step up gently: background < surface < panel (borders)."""

from __future__ import annotations

from textual.theme import Theme

THEMES = [
    Theme(name="mc-dark", dark=True, primary="#F0795B", accent="#F0795B", secondary="#B4A7F5",
          foreground="#D8DAE0", background="#0E0F13", surface="#15171C", panel="#2A2D37",
          success="#8CCB8C", warning="#E7C07B", error="#EB6F6F"),
    Theme(name="mc-dusk", dark=True, primary="#7AC4E6", accent="#7AC4E6", secondary="#C3A6F2",
          foreground="#CFD8E3", background="#151A22", surface="#1B212B", panel="#2E3746",
          success="#94CF93", warning="#E6C47F", error="#E68080"),
    Theme(name="mc-light", dark=False, primary="#C2410C", accent="#C2410C", secondary="#6D4FC2",
          foreground="#1F1D1A", background="#FAF9F7", surface="#F1EFEB", panel="#D9D5CE",
          success="#15803D", warning="#A16207", error="#B91C1C"),
]
BY_NAME = {theme.name: theme for theme in THEMES}
DEFAULT = THEMES[0].name
