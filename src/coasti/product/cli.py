from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Annotated, Any

import copier
import typer
from rich.console import Console
from rich.table import Table
from ruamel.yaml import YAML

from coasti.cli_context import ensure_coasti_namespace
from coasti.git import can_access_git_repo, copier_git_injection
from coasti.logger import log
from coasti.prompt import (
    prompt_like_copier,
    prompt_single,
)

from .product import Product, ProductsYamlIO
from .questions import PRODUCT_QUESTIONS

yaml = YAML()
app = typer.Typer()


def ensure_base_dir(ctx: typer.Context):
    """Check the CoastiContext has a base_dir valid for managing products."""

    coasti_ctx = ensure_coasti_namespace(ctx)

    # use getattr / setattr because for now, we dont want this attr to be part of
    # the global coasti context type
    if getattr(coasti_ctx, "base_dir_valid", False):
        return coasti_ctx

    base_dir = Path(os.getenv("COASTI_BASE_DIR", coasti_ctx.base_dir)).absolute()

    dir_is_valid = (base_dir / "config" / "products.yml").is_file()
    if not dir_is_valid and not coasti_ctx.quiet:
        base_dir = Path(
            prompt_single(
                help="Specify the coasti directory (cd there or set COASTI_BASE_DIR "
                "env var to avoid this prompt)",
                type=str,
                default="/coasti",
                # FIXME: add validator so these kind of checks can trigger re-prompt
            )
        ).absolute()
        dir_is_valid = (base_dir / "config" / "products.yml").is_file()

    if not dir_is_valid:
        log.error(f"Invalid coasti base dir: {str(base_dir)}")
        raise typer.Exit(code=1)

    coasti_ctx.base_dir = base_dir
    setattr(coasti_ctx, "base_dir_valid", True)

    return coasti_ctx


@app.command()
def list(ctx: typer.Context):
    """List installed products"""

    table = Table(title="Installed Products")
    table.add_column("Product", style="cyan", no_wrap=True)
    table.add_column("Property", style="magenta", justify="right")
    table.add_column("Value", style="green")

    coasti_ctx = ensure_base_dir(ctx)

    yaml_io = ProductsYamlIO(coasti_ctx.base_dir)
    for pid in yaml_io.product_ids:
        p = yaml_io.get_enry(pid)
        for idx, (key, value) in enumerate(p.items()):
            table.add_row(
                p["id"] if idx == 0 else "",
                key,
                str(value),
                end_section=(idx == len(p) - 1),
            )

    console = Console()
    console.print(table)


@app.command()
def add(
    ctx: typer.Context,
    vcs_repo: Annotated[
        str | None,
        typer.Argument(
            help="Url of the product's git repo.",
        ),
    ] = None,
    data: Annotated[
        str | None,
        typer.Option(
            "--data",
            help="Avoid prompts by providing answers as a JSON object like: "
            ' \'{"vcs_ref": "my_dev_branch"}\'',
        ),
    ] = None,
):
    """Add a product to coasti"""

    coasti_ctx = ensure_base_dir(ctx)

    # Parse skip-prompt answers and internal variables for answers_file
    questions = deepcopy(PRODUCT_QUESTIONS)
    extra_data: dict = {}
    if data is not None:
        try:
            extra_data = json.loads(data)
        except json.JSONDecodeError as e:
            log.error(f"Invalid JSON in --data: {e}")
            log.error(f"Input was: {data!r}")
            raise typer.Exit(code=1)

    copier_data: dict[str, Any] = {}
    copier_data.update(extra_data)

    vcs_repo = (
        vcs_repo
        or extra_data.get("vcs_repo")
        or prompt_single("Url of the product's git repo:", type=str)
    )
    copier_data.update({"vcs_repo": vcs_repo})

    # check if you can access the git repo
    if not can_access_git_repo(vcs_repo):
        log.info("Failed to access repo without authentication.")
        questions["vcs_auth_type"]["choices"].remove("skip")
        questions["vcs_auth_type"]["default"] = "Auth Token"
    else:
        questions["vcs_auth_type"]["help"] = (
            "Optional: " + questions["vcs_auth_type"]["help"]
        )

    yaml_io = ProductsYamlIO(coasti_ctx.base_dir)
    p_res = prompt_like_copier(
        questions=questions,
        data=copier_data,
    )
    product = Product(yaml_io=yaml_io, data=p_res)

    # FIXME: add single prompt verification via function so we can verify in place
    with copier_git_injection(
        https_token=product.vcs_auth_token,
        ssh_key_path=product.vcs_auth_sshkeypath,
    ):
        if not can_access_git_repo(vcs_repo):
            log.error("Could not access repo, despite authentication.")
            raise typer.Exit(code=1)

    if product.id in yaml_io.product_ids:
        if coasti_ctx.quiet or not prompt_single(
            f"Product id {product.id} already exists. Overwrite?",
            type=bool,
            default=True,
        ):
            log.info("Not overwriting product, exciting.")
            raise typer.Exit(code=1)

    product.write()

    if not coasti_ctx.quiet and prompt_single(
        f"Do you want to install {product.id} now?", type=bool, default=True
    ):
        install(ctx, product.id)


@app.command()
def install(
    ctx: typer.Context,
    pid: Annotated[
        str | None,
        typer.Argument(
            help="Id of the product.",
        ),
    ] = None,
):
    """
    Fetch resources for a product that has already been added

    Uses copier, git and details from config/products.yml
    """
    coasti_ctx = ensure_base_dir(ctx)

    yaml_io = ProductsYamlIO(coasti_ctx.base_dir)
    pid = _product_id_from_yaml_or_prompt(yaml_io, pid)
    try:
        product = yaml_io.get_product(pid)
        product.install()
    except copier.ProcessExecutionError as e:
        log.error(f"Failed to install {pid}. Check your connection and authentication.")
        log.info(e)
        raise typer.Exit(code=1)
    except Exception as e:
        # use typer to exit and avoid stack trace (which might contain auth info).
        log.error(e)
        raise typer.Exit(code=1)


@app.command()
def update(
    ctx: typer.Context,
    pid: Annotated[
        str | None,
        typer.Argument(
            help="Id of the product.",
        ),
    ] = None,
    vcs_ref: Annotated[
        str | None,
        typer.Option(
            "--vcs-ref", help="Version control reference, e.g. git branch or commit"
        ),
    ] = None,
):
    """
    Update an installed product

    Uses copier, git and details from config/products.yml
    """
    coasti_ctx = ensure_base_dir(ctx)

    yaml_io = ProductsYamlIO(coasti_ctx.base_dir)
    pid = _product_id_from_yaml_or_prompt(yaml_io, pid)
    try:
        product = yaml_io.get_product(pid)

        if vcs_ref is None:
            vcs_ref = product.data["vcs_ref"]

        product.update(vcs_ref)
    except copier.ProcessExecutionError as e:
        log.error(f"Failed to update {pid}. Check your connection and authentication.")
        log.info(e)
        raise typer.Exit(code=1)
    except Exception as e:
        # use typer to exit and avoid stack trace (which might contain auth info).
        log.error(e)
        raise typer.Exit(code=1)


def _product_id_from_yaml_or_prompt(
    yaml_io: ProductsYamlIO,
    pid: str | None,
):
    if pid is None:
        pid = prompt_single(
            "Select the product to use:", type=str, choices=yaml_io.product_ids
        )

    if pid not in yaml_io.product_ids:
        log.error(
            f"{pid} not found in products. Available products are:\n"
            f"  {yaml_io.product_ids}"
        )
        raise typer.Exit(code=1)

    return pid
