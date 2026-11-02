"""Unit tests for coasti's Copier URL normalisation."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest
from copier._vcs import get_repo

import coasti.product.product as product_module
from coasti.git import sanitize_repo_url_for_copier
from coasti.product.product import Product, ProductsYamlIO


@pytest.mark.parametrize(
    ("repo_url", "expected"),
    [
        # self-hosted http(s) without .git: copier would treat it as a local dir
        (
            "https://git.example.org/org/product",
            "git+https://git.example.org/org/product",
        ),
        (
            "http://gitea.internal/org/product",
            "git+http://gitea.internal/org/product",
        ),
        # already a .git URL: leave as-is
        (
            "https://git.example.org/org/product.git",
            "https://git.example.org/org/product.git",
        ),
        # github/gitlab without suffix are handled by copier already
        ("https://github.com/org/product", "git+https://github.com/org/product"),
        # explicit git+ prefix must not be doubled
        (
            "git+https://git.example.org/org/product",
            "git+https://git.example.org/org/product",
        ),
        # ssh remotes are recognised by copier as-is
        (
            "git@git.example.org:org/product.git",
            "git@git.example.org:org/product.git",
        ),
        # local paths are valid templates and must not be touched
        ("/local/path/to/template", "/local/path/to/template"),
        ("~/templates/product", "~/templates/product"),
    ],
)
def test_copier_src_path(repo_url: str, expected: str):
    assert sanitize_repo_url_for_copier(repo_url) == expected


def test_normalised_url_is_recognised_by_copier():
    """The whole point: copier must stop treating the URL as a local directory."""

    repo_url = "https://git.example.org/org/product"

    # Documents the copier heuristic that causes
    # "Local template must be a directory."
    assert get_repo(repo_url) is None

    assert get_repo(sanitize_repo_url_for_copier(repo_url)) is not None


def test_install_passes_normalised_url_to_copier(monkeypatch, tmp_path: Path):
    """Verify the wiring: Product.install feeds Copier the git+ URL."""

    captured: dict = {}

    monkeypatch.setattr(
        product_module.copier, "run_copy", lambda **kwargs: captured.update(kwargs)
    )
    monkeypatch.setattr(
        product_module, "copier_git_injection", lambda **kwargs: nullcontext()
    )
    monkeypatch.setattr(Product, "_create_symlinks", lambda self: None)

    product = Product(
        yaml_io=ProductsYamlIO(tmp_path),
        data={
            "vcs_repo": "https://git.example.org/org/product",
            "id": "product",
            "dst_path": "products/product",
            "vcs_ref": "",
            "vcs_auth_type": "skip",
            "vcs_auth_value": "__skip__",
        },
    )

    product.install()

    assert captured["src_path"] == "git+https://git.example.org/org/product"
