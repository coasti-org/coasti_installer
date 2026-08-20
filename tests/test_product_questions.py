from __future__ import annotations

import pytest

from coasti.product.questions import PRODUCT_QUESTIONS
from coasti.prompt import _jinja_env_like_copier


@pytest.mark.parametrize(
    ("vcs_repo", "expected"),
    [
        ("https://github.com/coasti-org/superset_docker.git", "superset_docker"),
        # a `trim('\.git$')` filter would strip any trailing character of
        # "\.git$" and mangle these two: "my_produc" and "ool"
        ("https://example.org/org/my_product.git", "my_product"),
        ("https://example.org/org/tool.git", "tool"),
        # ssh remotes and urls without the .git suffix
        ("git@github.com:coasti-org/superset_docker.git", "superset_docker"),
        ("https://github.com/coasti-org/superset_docker", "superset_docker"),
    ],
)
def test_product_id_default_is_repo_name_without_git_suffix(
    vcs_repo: str, expected: str
):
    """The default product id is derived from the repo url."""

    template = _jinja_env_like_copier().from_string(PRODUCT_QUESTIONS["id"]["default"])

    assert template.render(vcs_repo=vcs_repo) == expected
