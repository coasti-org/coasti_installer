# Integration tests

These tests exercise Coasti against disposable services instead of mocks. The
Gitea fixtures start a pinned Gitea container, create a private README-only
repository, and publish the mock product template as another repository. The
tests verify real access using both an HTTP token and an SSH key.

Docker must be running. From the repository root, run:

```text
uv run pytest -m integration tests/integration
```

Run the complete test suite with:

```text
uv run pytest
```

The container and its repositories are created for the test session and removed
afterwards. No repository or credentials are kept in the repository.
