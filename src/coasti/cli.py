from typing import Annotated

import typer
from superset_io.cli import app as superset_io_app

from coasti.logger import log, setup_logging_handler

from .init import app as init_app
from .product import app as product_app

app = typer.Typer()


@app.callback()
def main(
    ctx: typer.Context,
    verbose: Annotated[
        int,
        typer.Option(
            "--verbose",
            "-v",
            count=True,
            help="Increase verbosity (-v, -vv, -vvv)",
        ),
    ] = 0,
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet",
            "-q",
            help="Avoid user prompts",
        ),
    ] = False,
):
    """Coasti Installer - Initialize projects and install products."""
    setup_logging_handler(verbose)
    app.pretty_exceptions_short = False

    # Store shared state for all subcommands:
    ctx.ensure_object(dict)
    ctx.obj["quiet"] = quiet


@app.command()
def version():
    """Shows the version of the coasti installer."""
    log.info(f"Coasti version {get_version()}")


def get_version():
    from importlib import metadata

    try:
        return metadata.version("coasti")
    except metadata.PackageNotFoundError:
        return "[not found] Use `uv sync` when developing!"


app.add_typer(init_app)  # only one command so far
app.add_typer(product_app, name="product", help="List, add or update products.")
app.add_typer(
    superset_io_app,
    name="superset-io",
    help="Import or export superset frontend assets.",
)
