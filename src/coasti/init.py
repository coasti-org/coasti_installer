"""
`coasti init`

Initialize project structure.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from importlib import metadata, resources
from pathlib import Path
from typing import Annotated, Any

import copier
import typer
from platformdirs import user_cache_dir

from coasti.git import get_git_or_exit
from coasti.prompt import prompt_single

from .logger import log

app = typer.Typer()


@app.command()
def init(
    coasti_dir: Annotated[
        Path | None,
        typer.Argument(
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            writable=True,
            help="Where to place coasti?",
        ),
    ] = None,
    recopy: Annotated[
        bool,
        typer.Option(
            "--recopy",
            help="If target exists, re-copy instead of updating. Ignores git changes.",
        ),
    ] = False,
    vcs_ref: Annotated[
        str | None,
        typer.Option(
            "--vcs-ref",
            help="Specify the VCS tag/commit of the coasti template (dev option).",
        ),
    ] = None,
    data: Annotated[
        str | None,
        typer.Option(
            "--data",
            help="Avoid prompts by providing answers as a JSON object like: "
            ' \'{"vcs_repo_type": "skip"}\'',
        ),
    ] = None,
):
    """Initialize a coasti workspace"""

    # coasti init uses copier, which needs git
    get_git_or_exit()

    # Parse skip-prompt answers and internal variables for answers_file
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
    copier_data.update({"coasti_version": metadata.version("coasti")})

    if coasti_dir is None:
        coasti_dir = prompt_single(
            "Where to place coasti?", type=Path, default=Path.cwd() / "coasti"
        )

    # even when updating, we need the repo version on disk.
    # we need to make sure the _src_path stays the same in the answers (or mod it).
    template_repo = materialize_template_repo()

    try:
        if (coasti_dir / "config" / "install_answers.yml").exists() and not recopy:
            log.debug(f"Using copier update on {coasti_dir}")
            copier.run_update(
                dst_path=coasti_dir,
                answers_file="./config/install_answers.yml",
                data=copier_data,
                vcs_ref=vcs_ref,
                unsafe=True,
                overwrite=True,
            )
        else:
            log.debug(
                f"Using copier copy on {coasti_dir} with template from "
                f"{str(template_repo)}"
            )
            copier.run_copy(
                src_path=str(template_repo),
                dst_path=coasti_dir,
                answers_file="./config/install_answers.yml",
                data=copier_data,
                vcs_ref=vcs_ref,
                unsafe=True,
            )
    except copier.ProcessExecutionError as e:
        log.error("Failed to init from template")
        log.info(e)


def materialize_template_repo() -> Path:
    """
    Ensure a cached on-disk git repo exists that was cloned from the shipped bundle.
    Returns the repo directory path.
    """

    cache_dir = Path(user_cache_dir("coasti", "template-repo"))
    cache_dir.mkdir(parents=True, exist_ok=True)

    repo_dir = cache_dir / "repo"
    if repo_dir.exists():
        log.debug("Removing old template repo.")
        _ensure_writable(repo_dir)
        shutil.rmtree(repo_dir)
        # lets keep this simple for now. we can later add checks to avoid copying.
        # however, requires version checks
    log.debug(f"Materializing template repo at {str(repo_dir)}")

    bundle_resource = _get_template_bundle_path()
    with resources.as_file(bundle_resource) as bundle_path:
        subprocess.check_call(
            ["git", "clone", "--quiet", str(bundle_path), str(repo_dir)]
        )

    return repo_dir


def _get_template_bundle_path():
    """Location where the template bundle is expected.

    Separate function for easy mocking in tests.
    """
    return resources.files("coasti._bundles").joinpath("template-repo.bundle")


def _ensure_writable(path: Path) -> None:
    """Workaround for windows, where rmtree throws an error on .git folders."""
    for root, dirs, files in os.walk(path, topdown=True):
        for d in dirs:
            (Path(root) / d).chmod(stat.S_IWRITE | stat.S_IRWXU)
        for f in files:
            (Path(root) / f).chmod(stat.S_IWRITE)
