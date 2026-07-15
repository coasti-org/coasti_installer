"""
We use a typed context object, for typers ctx.obj.

This is set on the top-level command, and is accessible in all subcommands.
"""

from dataclasses import dataclass
from pathlib import Path

import typer


@dataclass
class CoastiContextNamespace:
    """Typed context that has attributes needed for a few coasti commands."""

    # _all_ attributes subcommands can use are collected here:
    quiet: bool = False
    base_dir: Path = Path.cwd().absolute()


def ensure_coasti_namespace(ctx: typer.Context) -> CoastiContextNamespace:
    """Make sure that typer contexts' object is a coasti namespace."""

    if isinstance(ctx.obj, CoastiContextNamespace):
        return ctx.obj
    elif ctx.obj is not None:
        raise TypeError(
            f"Unexpected context object type: {type(ctx.obj)!r}. "
            "Expected CoastiContextNamespace or None."
        )
    else:
        ctx.obj = CoastiContextNamespace()

    return ctx.obj
