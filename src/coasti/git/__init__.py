import shlex
import sys
from collections.abc import Collection, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import Any

import copier._vcs as copier_vcs
import typer
from plumbum.commands.processes import (
    CommandNotFound,
    ProcessExecutionError,
    ProcessTimedOut,
)

from coasti.logger import log


@contextmanager
def copier_git_injection(
    *,
    https_token: str | None = None,
    ssh_key_path: str | Path | None = None,
    ssh_known_hosts_path: str | Path | None = None,
) -> Generator[None]:
    """
    Inject auth settings into all git commands executed by Copier.

    - https_token: used for HTTPS clones/fetches via GIT_ASKPASS.
    - ssh_key_path: absolute path to an SSH private key to force for SSH clones/fetches.

    We monkeypatch copiers get_git() command to keep env vars in a small scope.

    Example
    ```
    with copier_git_injection(https_token=vcs_auth_token):
        can_access_git_repo(repo_ulr)
    ```
    """
    if ssh_key_path is not None and https_token is not None:
        raise ValueError("Provide either https_token or ssh_key_path")

    if ssh_key_path is not None and not Path(ssh_key_path).is_absolute():
        raise ValueError("ssh_key_path must be an absolute path")

    original_get_git = copier_vcs.get_git

    try:
        extra_env: dict[str, Any] = {}
        log.debug(
            "Git injection requested: "
            f"platform={sys.platform}, "
            f"https_token={'set' if https_token else 'unset'}, "
            f"ssh_key_path={ssh_key_path!s}, "
            f"ssh_known_hosts_path={ssh_known_hosts_path!s}"
        )

        if https_token:
            with resources.as_file(
                resources.files("coasti.git").joinpath(
                    "askpass" + (".bat" if sys.platform == "win32" else ".sh")
                )
            ) as askpass_script:
                extra_env["GIT_ASKPASS"] = str(askpass_script)
                # scripts simply return the token env var
                askpass_script_exists = Path(askpass_script).is_file()

            extra_env["GIT_AUTH_TOKEN"] = https_token

            # Some git flows require the following to force askpass in non-tty contexts,
            # or gui popups (git-for-windows)
            extra_env["GIT_TERMINAL_PROMPT"] = "0"
            extra_env["GCM_INTERACTIVE"] = "false"
            log.debug(
                f"Configured Git askpass script: {askpass_script}; "
                f"exists={askpass_script_exists}"
            )

        elif ssh_key_path:
            if Path(ssh_key_path).is_file():
                extra_env["GIT_SSH_COMMAND"] = (
                    f"ssh -i {shlex.quote(Path(ssh_key_path).as_posix())} "
                    "-o IdentitiesOnly=yes"
                )
                if ssh_known_hosts_path is not None:
                    extra_env["GIT_SSH_COMMAND"] += (
                        " -o UserKnownHostsFile="
                        f"{shlex.quote(Path(ssh_known_hosts_path).as_posix())}"
                        " -o StrictHostKeyChecking=yes"
                    )
                log.debug(f"Configured Git SSH command: {extra_env['GIT_SSH_COMMAND']}")
            else:
                # avoid Prompt injection, skip ssh overwrite
                log.warning(f"'{ssh_key_path}' is not a valid path for an ssh key.")

        def patched_get_git(*args, **kwargs):
            git = original_get_git()
            # Attach env to the command object.
            # (Plumbum supports cmd.with_env(VAR=...))
            cmd = git.with_env(**extra_env) if extra_env else git
            log.debug(f"using git command: {cmd=} {extra_env=}")
            return cmd

        copier_vcs.get_git = patched_get_git
        yield
    finally:
        copier_vcs.get_git = original_get_git


class GitAccessFailure(StrEnum):
    """Reason a Git repository access probe failed."""

    AUTHENTICATION = "authentication"
    HOST_VERIFICATION = "host_verification"
    TLS_CERTIFICATE = "tls_certificate"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    NETWORK = "network"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GitProbeResult:
    """Outcome of a Git repository access probe.

    Truthiness intentionally mirrors the former boolean return value so callers
    can migrate to inspecting failure details without changing control flow.
    """

    is_accessible: bool
    failure: GitAccessFailure | None = None
    detail: str | None = None

    def __bool__(self) -> bool:
        return self.is_accessible

    def exit_for_failures_except(
        self,
        failures_not_to_raise: Collection[GitAccessFailure] = frozenset(),
    ) -> None:
        """Log and exit for a failure unless it is explicitly exempted."""

        if self.failure is None or self.failure in failures_not_to_raise:
            return

        messages: dict[GitAccessFailure, str] = {
            GitAccessFailure.AUTHENTICATION: (
                "Git authentication failed. Check your credentials and try again."
            ),
            GitAccessFailure.HOST_VERIFICATION: (
                "Git rejected the SSH host key. Add the host to your SSH known_hosts "
                "file and try again."
            ),
            GitAccessFailure.TLS_CERTIFICATE: (
                "Git rejected the server certificate. Check your TLS or certificate "
                "configuration and try again."
            ),
            GitAccessFailure.TIMEOUT: (
                "Git timed out while accessing the repository. Try again later."
            ),
            GitAccessFailure.NETWORK: (
                "Git could not reach the repository. Check the URL and network."
            ),
            GitAccessFailure.NOT_FOUND: (
                "Git could not find the repository. Check the repository URL."
            ),
            GitAccessFailure.UNKNOWN: (
                "Git could not access the repository. Check the URL and Git "
                "configuration."
            ),
        }
        log.error(messages[self.failure])
        raise typer.Exit(code=1)


def check_access_to_git_repo(
    repo_url: str,
    *,
    timeout_seconds: float = 15,
) -> GitProbeResult:
    """
    Probe if we can reach a repo using Copier's git command.

    This is a *non-authenticated* probe:
    - no tokens
    - no ssh key overrides
    - relies only on whatever git/ssh is already configured on the machine

    Implementation: `git ls-remote <repo_url> -q`
    """

    cmd = copier_vcs.get_git()["ls-remote", str(repo_url), "-q"]
    try:
        _code, _stdout, _stderr = cmd.run(timeout=timeout_seconds)
        return GitProbeResult(is_accessible=True)
    except ProcessTimedOut:
        log.debug(
            f"Git repo access check timed out after {timeout_seconds}: {repo_url}"
        )
        return GitProbeResult(
            is_accessible=False,
            failure=GitAccessFailure.TIMEOUT,
            detail=f"Timed out after {timeout_seconds} seconds",
        )
    except ProcessExecutionError as e:
        stderr = (e.stderr or "").strip().replace("\n", " ")
        stdout = (e.stdout or "").strip().replace("\n", " ")
        code = e.retcode
        log.debug(f"Git repo access check failed: {code=} {stdout=} {stderr=}")
        detail = stderr or stdout

        def _classify_git_failure(_detail: str) -> GitAccessFailure:
            detail = _detail.lower()
            if "host key verification failed" in detail or (
                "authenticity of host" in detail
            ):
                return GitAccessFailure.HOST_VERIFICATION
            if "ssl certificate problem" in detail:
                return GitAccessFailure.TLS_CERTIFICATE
            if "repository not found" in detail:
                return GitAccessFailure.NOT_FOUND
            if "authentication failed" in detail or "permission denied" in (detail):
                return GitAccessFailure.AUTHENTICATION
            if any(
                message in detail
                for message in (
                    "could not resolve host",
                    "connection refused",
                    "network is unreachable",
                )
            ):
                return GitAccessFailure.NETWORK
            return GitAccessFailure.UNKNOWN

        return GitProbeResult(
            is_accessible=False,
            failure=_classify_git_failure(detail),
            detail=detail or None,
        )


def get_git_or_exit():
    """
    Get the git executable, or exit the coasti app.

    Without git, most commands around copier wont work.
    """

    try:
        git_command = copier_vcs.get_git()
    except CommandNotFound:
        typer.echo(
            "Git is required for most coasti commands but was not found on the PATH. "
            "Please install Git and try again.",
            err=True,
        )
        raise typer.Exit(code=1) from None

    required_config = ("init.defaultBranch", "user.email", "user.name")
    missing_config: list[str] = []

    for config_name in required_config:
        try:
            _code, stdout, _stderr = git_command[
                "config", "--global", "--get", config_name
            ].run()
        except ProcessExecutionError:
            missing_config.append(config_name)
            continue

        config_value = stdout.strip()
        if not config_value:
            missing_config.append(config_name)

    if missing_config:
        required_commands = {
            "init.defaultBranch": "  git config --global init.defaultBranch main",
            "user.email": '  git config --global user.email "you@example.com"',
            "user.name": '  git config --global user.name "Your Name"',
        }
        log.warning(
            "Coasti requires git. We found the executable, but your configuration is "
            "missing some details. Add them to avoid issues:\n"
            + "\n".join(
                required_commands[config_name] for config_name in missing_config
            )
            + "\n",
        )

    return git_command
