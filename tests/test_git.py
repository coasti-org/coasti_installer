"""Unit tests for the git command wrappers.

These do not touch the network: they assert the environment/flags coasti passes
to git, which is what keeps git from prompting for credentials.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from plumbum.commands.processes import ProcessExecutionError

import coasti.git as git
from coasti.git import (
    NON_INTERACTIVE_GIT_ENV,
    GitAccessFailure,
    check_access_to_git_repo,
    classify_git_failure,
    copier_git_injection,
)


class RecordingGit:
    """Minimal stand-in for a plumbum command that records env and args."""

    instances: list[RecordingGit] = []
    get_git_calls: list[tuple[tuple, dict]] = []

    def __init__(self, env: dict[str, str] | None = None, args: tuple = ()):
        self.env = dict(env or {})
        self.args = tuple(args)
        self.ran = False
        RecordingGit.instances.append(self)

    def with_env(self, **env: str) -> RecordingGit:
        merged = dict(self.env)
        merged.update(env)
        return type(self)(merged, self.args)

    def __getitem__(self, args) -> RecordingGit:
        if not isinstance(args, tuple):
            args = (args,)
        return type(self)(self.env, self.args + tuple(args))

    def run(self, *args, **kwargs):
        self.ran = True
        return (0, "", "")


def _install_recording_git(monkeypatch) -> list[RecordingGit]:
    """Patch copier's get_git to hand out RecordingGit instances."""

    RecordingGit.instances = []
    RecordingGit.get_git_calls = []

    def get_git(*args, **kwargs) -> RecordingGit:
        RecordingGit.get_git_calls.append((args, kwargs))
        return RecordingGit()

    monkeypatch.setattr(git.copier_vcs, "get_git", get_git)
    return RecordingGit.instances


def test_non_interactive_env_disables_all_prompt_sources():
    """The baseline env must cover git, GCM and ssh prompts."""

    assert NON_INTERACTIVE_GIT_ENV["GIT_TERMINAL_PROMPT"] == "0"
    assert NON_INTERACTIVE_GIT_ENV["GCM_INTERACTIVE"] == "false"
    assert NON_INTERACTIVE_GIT_ENV["SSH_ASKPASS_REQUIRE"] == "never"


def test_check_access_probe_never_prompts(monkeypatch):
    """The unauthenticated probe is the one that used to pop a git prompt."""

    created = _install_recording_git(monkeypatch)

    result = check_access_to_git_repo("https://example.invalid/repo.git")

    assert result.is_accessible
    probe = next(command for command in created if command.ran)
    assert probe.args == (
        "ls-remote",
        "https://example.invalid/repo.git",
        "-q",
    )
    for key, value in NON_INTERACTIVE_GIT_ENV.items():
        assert probe.env[key] == value


def test_copier_git_injection_with_https_token(monkeypatch):
    """The token is offered via askpass, without disabling ambient helpers."""

    _install_recording_git(monkeypatch)

    with copier_git_injection(https_token="secret-token"):
        # get_git is monkeypatched, but its static type is plumbum's BaseCommand.
        command = cast(RecordingGit, git.copier_vcs.get_git())

    assert command.env["GIT_AUTH_TOKEN"] == "secret-token"
    assert command.env["GIT_ASKPASS"].endswith((".sh", ".bat"))
    for key, value in NON_INTERACTIVE_GIT_ENV.items():
        assert command.env[key] == value
    # We deliberately do *not* reset credential.helper: an ambient helper (e.g.
    # Git Credential Manager) keeps working and wins if it has a stored
    # credential, our token is only a fallback. It still cannot prompt, because
    # the env above disables GCM/terminal prompts.
    assert command.args == ()


def test_copier_git_injection_forwards_get_git_arguments(monkeypatch):
    """copier calls get_git(context_dir=...); the patched version must not eat it."""

    _install_recording_git(monkeypatch)
    template_dir = Path("/some/template")

    with copier_git_injection(https_token="secret-token"):
        git.copier_vcs.get_git(context_dir=template_dir)

    assert RecordingGit.get_git_calls == [((), {"context_dir": template_dir})]


def test_copier_git_injection_with_ssh_key_disables_prompts(
    monkeypatch, tmp_path: Path
):
    _install_recording_git(monkeypatch)
    key = tmp_path / "id_ed25519"
    key.write_text("not a real key")

    with copier_git_injection(ssh_key_path=key):
        command = cast(RecordingGit, git.copier_vcs.get_git())

    assert "GIT_AUTH_TOKEN" not in command.env
    assert "GIT_ASKPASS" not in command.env
    assert "-i" in command.env["GIT_SSH_COMMAND"]
    for key_name, value in NON_INTERACTIVE_GIT_ENV.items():
        assert command.env[key_name] == value


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        (
            "fatal: could not read Username for 'https://github.com': "
            "terminal prompts disabled",
            GitAccessFailure.AUTHENTICATION,
        ),
        (
            "fatal: Authentication failed for 'https://example.org/x.git/'",
            GitAccessFailure.AUTHENTICATION,
        ),
        ("remote: Invalid username or password", GitAccessFailure.AUTHENTICATION),
        ("fatal: repository not found", GitAccessFailure.NOT_FOUND),
        ("Host key verification failed.", GitAccessFailure.HOST_VERIFICATION),
        (
            "SSL certificate problem: unable to get local issuer",
            GitAccessFailure.TLS_CERTIFICATE,
        ),
        ("Could not resolve host: github.com", GitAccessFailure.NETWORK),
        ("something we do not recognise", GitAccessFailure.UNKNOWN),
    ],
)
def test_classify_git_failure(detail: str, expected: GitAccessFailure):
    assert classify_git_failure(detail) is expected


def test_probe_classifies_disabled_prompt_as_authentication(monkeypatch):
    """A private https repo now fails as AUTHENTICATION so coasti asks for a token."""

    class FailingGit(RecordingGit):
        def run(self, *args, **kwargs):
            raise ProcessExecutionError(
                argv=["git", "ls-remote"],
                retcode=128,
                stdout="",
                stderr=(
                    "fatal: could not read Username for 'https://example.invalid': "
                    "terminal prompts disabled"
                ),
            )

    monkeypatch.setattr(git.copier_vcs, "get_git", lambda: FailingGit())

    result = check_access_to_git_repo("https://example.invalid/private.git")

    assert not result.is_accessible
    assert result.failure is GitAccessFailure.AUTHENTICATION
