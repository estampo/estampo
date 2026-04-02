"""Rich UI helpers for interactive CLI commands."""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import Console, ConsoleRenderable, RichCast
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.status import Status
from rich.syntax import Syntax
from rich.table import Table
from rich.theme import Theme

_THEME = Theme(
    {
        "info": "cyan",
        "success": "green",
        "warning": "yellow",
        "error": "red bold",
        "heading": "bold cyan",
    }
)

console = Console(highlight=False, theme=_THEME)


def heading(text: str) -> None:
    """Print a section heading with a rule line."""
    console.rule(f"[heading]{text}[/heading]", style="dim")


def success(text: str) -> None:
    """Print a success line with green checkmark."""
    console.print(f"  [green]\u2714[/green] {text}")


def warn(text: str) -> None:
    """Print a warning line."""
    console.print(f"  [yellow]\u26a0[/yellow] {text}")


def error(text: str) -> None:
    """Print an error line."""
    console.print(f"  [red]\u2718[/red] {text}")


def info(text: str) -> None:
    """Print an info line."""
    console.print(f"  [dim]{text}[/dim]")


_active_status: Status | None = None


class _StatusContext:
    """Context manager that updates a running spinner or starts a new one.

    Only one Rich Status spinner can render at a time.  If a spinner is
    already active (e.g. the pipeline adapter) we update its message
    instead of creating a competing spinner that causes flicker.
    """

    def __init__(self, message: str) -> None:
        self._message = f"  {message}"
        self._owned: Status | None = None
        self._prev_renderable: ConsoleRenderable | RichCast | str | None = None

    def __enter__(self):  # noqa: ANN204
        global _active_status  # noqa: PLW0603

        if _active_status is not None:
            # Another spinner is running — update its label, restore later
            self._prev_renderable = _active_status.status
            _active_status.update(self._message)
        else:
            self._owned = console.status(self._message, spinner="dots")
            self._owned.__enter__()
            _active_status = self._owned
        return self

    def __exit__(self, *exc):  # noqa: ANN002
        global _active_status  # noqa: PLW0603

        if self._owned is not None:
            self._owned.__exit__(*exc)
            _active_status = None
        elif self._prev_renderable is not None and _active_status is not None:
            _active_status.update(self._prev_renderable)
        return False


def status(message: str) -> _StatusContext:
    """Return a context manager that shows a Rich Status spinner.

    If a spinner is already active, updates its message instead of
    creating a second spinner (which causes flicker).

    Usage::

        with ui.status("Pulling Docker image"):
            do_slow_thing()
    """
    return _StatusContext(message)


def prompt_str(prompt: str, default: str | None = None) -> str:
    """Prompt for a string value with optional default."""
    result = Prompt.ask(f"  {prompt}", default=default, console=console)
    return result or ""


def prompt_int(prompt: str, default: int) -> int:
    """Prompt for an integer with a default."""
    return IntPrompt.ask(f"  {prompt}", default=default, console=console)


def prompt_yn(prompt: str, default: bool = True) -> bool:
    """Prompt yes/no with a default."""
    return Confirm.ask(f"  {prompt}", default=default, console=console)


def prompt_password(prompt: str) -> str:
    """Prompt for a password (masked input)."""
    return Prompt.ask(f"  {prompt}", password=True, console=console) or ""


def preview_toml(text: str) -> None:
    """Show TOML content with syntax highlighting in a panel."""
    syntax = Syntax(text, "toml", theme="monokai", line_numbers=False)
    console.print(Panel(syntax, title="estampo.toml", border_style="dim"))


def choice_table(
    items: Sequence[Sequence[str]],
    columns: list[str],
    *,
    markup: bool = False,
) -> None:
    """Print a numbered selection table.

    Set ``markup=True`` to allow Rich markup in cell values (e.g. colors).
    By default all values are escaped to prevent accidental markup injection.
    """
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("#", style="dim", width=4)
    for col in columns:
        table.add_column(col)
    for i, row in enumerate(items, 1):
        cells = row if markup else tuple(escape(c) for c in row)
        table.add_row(str(i), *cells)
    console.print(table)


def color_swatch(hex_color: str) -> str:
    """Return a Rich markup string for a colored swatch block."""
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"[on rgb({r},{g},{b})]  [/on rgb({r},{g},{b})]"


# ---------------------------------------------------------------------------
# Interactive picker
# ---------------------------------------------------------------------------


def pick(
    options: list[str],
    prompt: str = "Pick",
    allow_multi: bool = False,
) -> list[int]:
    """Interactive picker with type-to-search filtering.

    Uses ``questionary`` (prompt_toolkit) for terminal UI.
    Returns a list of indices into the original *options* list.
    """
    import questionary

    if allow_multi:
        selected = questionary.checkbox(
            f"  {prompt}",
            choices=options,
        ).ask()
    else:
        selected_value = questionary.select(
            f"  {prompt}",
            choices=options,
            use_search_filter=True,
            use_jk_keys=False,
        ).ask()
        selected = [selected_value] if selected_value is not None else None

    if selected is None:
        raise KeyboardInterrupt

    indices = []
    for val in selected:
        idx = options.index(val)
        indices.append(idx)
        success(val)

    return indices
