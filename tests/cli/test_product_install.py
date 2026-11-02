"""CLI tests for commands that need a product id but may be called without one."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import coasti.cli as cli
import coasti.product.product as product_module
from coasti.product.cli import _product_id_from_yaml_or_prompt
from coasti.product.product import ProductsYamlIO

PRODUCTS_YAML = """\
products:
  - id: p1
    vcs_repo: https://example.org/org/p1.git
    vcs_ref: ''
    dst_path: products/p1
"""


class _StubPromptResponse:
    """Stand-in for PromptResponse; the fake question always answers "p1"."""

    answers = {"temp": "p1"}


@pytest.fixture
def coasti_base_dir(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "products.yml").write_text(PRODUCTS_YAML)
    return tmp_path


def _stub_prompting(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Patch the layer below prompt_single so the real prompt_single runs."""

    seen: dict = {}

    def fake_prompt_like_copier(questions):
        seen.update(questions)
        return _StubPromptResponse()

    monkeypatch.setattr(
        "coasti.prompt.prompt_like_copier", fake_prompt_like_copier, raising=True
    )
    return seen


def test_product_id_from_yaml_or_prompt_prompts_when_no_id_given(
    coasti_base_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: this prompt has no default and used to raise KeyError."""

    seen = _stub_prompting(monkeypatch)

    pid = _product_id_from_yaml_or_prompt(ProductsYamlIO(coasti_base_dir), None)

    assert pid == "p1"
    question = seen["temp"]
    assert "default" not in question
    assert question["choices"] == ["p1"]


def test_product_install_without_argument_installs_selected_product(
    cli_runner: CliRunner,
    coasti_base_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """`coasti product install` without an id must prompt, not crash."""

    _stub_prompting(monkeypatch)

    installed: list[str] = []
    monkeypatch.setattr(
        product_module.Product, "install", lambda self: installed.append(self.id)
    )

    result = cli_runner.invoke(
        cli.app,
        ["product", "install"],
        env={"COASTI_BASE_DIR": str(coasti_base_dir), "COLUMNS": "200"},
    )

    assert result.exit_code == 0, f"{result.exception!r}; {result.output!r}"
    assert installed == ["p1"]
