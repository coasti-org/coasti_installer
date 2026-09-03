from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import copier
import typer
from rich.console import Console
from rich.table import Table
from ruamel.yaml import YAML

from coasti.cli_context import ensure_coasti_namespace
from coasti.git import (
    GitAccessFailure,
    check_access_to_git_repo,
    copier_git_injection,
    get_git_or_exit,
)
from coasti.logger import log
from coasti.prompt import (
    prompt_like_copier,
    prompt_single,
)

from .product import Product, ProductsYamlIO
from .questions import (
    AUTH_QUESTIONS,
    AUTH_SKIP_SENTINEL,
    PRODUCT_QUESTIONS,
    ProductData,
)

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

    get_git_or_exit()
    coasti_ctx = ensure_base_dir(ctx)
    yaml_io = ProductsYamlIO(coasti_ctx.base_dir)

    # Parse skip-prompt answers and internal variables for answers_file

    extra_data: ProductData = {}  # type: ignore # so be defensive!
    if data is not None:
        try:
            extra_data = json.loads(data)
        except json.JSONDecodeError as e:
            log.error(f"Invalid JSON in --data: {e}")
            log.error(f"Input was: {data!r}")
            raise typer.Exit(code=1)

    product = Product.draft(yaml_io)
    product.data.update(extra_data)
    repository_url = vcs_repo or product.data.get("vcs_repo")

    while True:
        if repository_url is None:
            repository_url = prompt_single("Url of the product's git repo:", type=str)

        probe = check_access_to_git_repo(repository_url)
        if probe.is_accessible:
            product.data["vcs_repo"] = repository_url
            product.data["vcs_auth_type"] = "skip"
            product.data["vcs_auth_value"] = AUTH_SKIP_SENTINEL
            break

        probe.exit_for_failures_except({GitAccessFailure.AUTHENTICATION})

        # Ask authentication questions
        log.info("Failed to access repo without authentication.")

        auth_response = prompt_like_copier(
            questions=AUTH_QUESTIONS,
            data={**extra_data, "vcs_repo": repository_url},
        )

        log.debug(f"{auth_response=}")

        product.data.update(
            {
                "vcs_repo": repository_url,
                "vcs_auth_type": auth_response.answers["vcs_auth_type"],
                "vcs_auth_value": auth_response.answers["vcs_auth_value"],
            }
        )

        log.debug(f"{product.data=}")
        log.debug(f"{product.vcs_auth_token=}, {product.vcs_auth_sshkeypath=}")

        with copier_git_injection(
            https_token=product.vcs_auth_token,
            ssh_key_path=product.vcs_auth_sshkeypath,
        ):
            probe = check_access_to_git_repo(repository_url)
            if probe.is_accessible:
                break

            probe.exit_for_failures_except({GitAccessFailure.AUTHENTICATION})

        log.error(
            "Could not access the repository with the provided authentication. "
            "Please check the URL or credentials and try again."
        )
        if ensure_coasti_namespace(ctx).quiet:
            raise typer.Exit(code=1)

        # Retry, and allow user to correct url and auth
        repository_url = None

    log.debug(f"{product.data=}")
    log.debug("Done with auth questions. Asking general questions")

    p_res = prompt_like_copier(
        questions=PRODUCT_QUESTIONS,
        data={**extra_data, "vcs_repo": product.data["vcs_repo"]},
    )
    product.data.update(p_res.answers)

    log.debug(f"{product.data=}")

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

    get_git_or_exit()
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
            "--vcs-ref",
            help="Version control reference, e.g. git branch or commit. "
            "Pass empty string to use the latest tagged version.",
        ),
    ] = None,
    pretend: Annotated[
        bool,
        typer.Option("--pretend", help="Run but do not make any changes"),
    ] = False,
    answers_file: Annotated[
        str | None,
        typer.Option(
            "--answers-file",
            help="Which answers file to use, relative to products (template) base dir. "
            "Leave empty try coastis default, then copiers default.",
        ),
    ] = None,
):
    """
    Update an installed product

    Uses copier, git and details from config/products.yml
    """

    get_git_or_exit()
    coasti_ctx = ensure_base_dir(ctx)

    yaml_io = ProductsYamlIO(coasti_ctx.base_dir)
    pid = _product_id_from_yaml_or_prompt(yaml_io, pid)
    try:
        product = yaml_io.get_product(pid)
        product.update(vcs_ref, pretend, answers_file=answers_file)
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
