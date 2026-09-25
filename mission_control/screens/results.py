"""Results: the selected run's folder as a file tree, with a preview. `e` opens a file in $EDITOR."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.timer import Timer
from textual.widgets import DirectoryTree, Markdown, TextArea, Tree

from mission_control.model import Run, Update
from mission_control.screens.base import View

MAX_PREVIEW_BYTES = 2_000_000
DEBOUNCE = 0.08
LANGUAGES = {".json": "json", ".jsonl": "json", ".py": "python", ".patch": "diff", ".diff": "diff",
             ".toml": "toml", ".yaml": "yaml", ".yml": "yaml", ".md": "markdown"}


def preview_text(path: Path) -> str:
    """A file as text for the preview: JSON pretty-printed, big or binary files described instead."""
    size = path.stat().st_size
    if size > MAX_PREVIEW_BYTES:
        return f"({size:,} bytes: too big to preview; press e to open it in your editor)"
    raw = path.read_bytes()
    if b"\0" in raw[:4096]:
        return f"(binary file, {size:,} bytes)"
    text = raw.decode("utf-8", errors="replace")
    if path.suffix == ".json":
        try:
            return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            return text
    return text


class ResultsScreen(View):
    TITLES: ClassVar[dict[str, str]] = {"#files": "Files", "#preview-md": "Preview", "#preview-text": "Preview"}
    BINDINGS: ClassVar[list[BindingType]] = [Binding("e", "edit", "Open in editor")]

    def __init__(self) -> None:
        super().__init__()
        self._run: Run | None = None
        self._path: Path | None = None
        self._timer: Timer | None = None

    def body(self) -> ComposeResult:
        with Horizontal():
            yield DirectoryTree(Path.cwd(), id="files")
            with VerticalScroll(id="preview-md"):
                yield Markdown()
            yield TextArea(read_only=True, soft_wrap=True, show_line_numbers=True, id="preview-text")

    def redraw(self, run: Run, updates: list[Update]) -> None:
        if run is self._run:
            return
        self._run = run
        files = self.query_one(DirectoryTree)
        files.path = run.path
        self.query_one("#files").border_title = f"Files · {run.path.name}"
        final = run.path / "final.md"
        self._show(final if final.exists() else None)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        path = getattr(event.node.data, "path", None)
        if path is None or not Path(path).is_file():
            return
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_timer(DEBOUNCE, lambda: self._show(Path(path)))

    def _show(self, path: Path | None) -> None:
        self._path = path
        markdown, text = self.query_one("#preview-md"), self.query_one("#preview-text", TextArea)
        is_md = path is not None and path.suffix == ".md"
        markdown.display, text.display = is_md, not is_md
        if path is None:
            text.load_text("Pick a file.")
            return
        title = f"Preview · {path.name}"
        markdown.border_title = text.border_title = title
        if is_md:
            self.query_one(Markdown).update(preview_text(path))
            markdown.scroll_home(animate=False)
            return
        text.load_text(preview_text(path))
        language = LANGUAGES.get(path.suffix)
        text.language = language if language in text.available_languages else None

    def action_edit(self) -> None:
        if self._path is None:
            return
        editor = shlex.split(os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano")
        with self.app.suspend():
            subprocess.run([*editor, str(self._path)], check=False)
