import shlex
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Any

import copier._vcs as copier_vcs
from plumbum.commands.processes import ProcessExecutionError, ProcessTimedOut

from coasti.logger import log


@contextmanager
def copier_git_injection(
    *,
    https_token: str | None = None,
    ssh_key_path: str | Path | None = None,
    ssh_known_hosts_path: str | Path | None = None,
) -> Iterator[None]:
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

        if https_token:
            with resources.as_file(
                resources.files("coasti.git").joinpath(
                    "askpass" + (".bat" if sys.platform == "win32" else ".sh")
                )
            ) as askpass_script:
                extra_env["GIT_ASKPASS"] = str(askpass_script)
                # scripts simply return the token env var

            extra_env["GIT_AUTH_TOKEN"] = https_token

            # Some git flows require the following to force askpass in non-tty contexts,
            # or gui popups (git-for-windows)
            extra_env["GIT_TERMINAL_PROMPT"] = "0"
            extra_env["GCM_INTERACTIVE"] = "false"

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
            else:
                # avoid Prompt injection, skip ssh overwrite
                log.warning(f"'{ssh_key_path}' is not a valid path for an ssh key.")

        def patched_get_git(*args, **kwargs):
            git = original_get_git()
            # Attach env to the command object.
            # (Plumbum supports cmd.with_env(VAR=...))
            cmd = git.with_env(**extra_env) if extra_env else git
            return cmd

        copier_vcs.get_git = patched_get_git
        yield
    finally:
        copier_vcs.get_git = original_get_git


def can_access_git_repo(repo_url: str, *, timeout_seconds: float = 15) -> bool:
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
        return True
    except ProcessTimedOut:
        log.debug(
            f"Git repo access check timed out after {timeout_seconds}: {repo_url}"
        )
        return False
    except ProcessExecutionError as e:
        stderr = (e.stderr or "").strip().replace("\n", " ")
        stdout = (e.stdout or "").strip().replace("\n", " ")
        code = e.retcode
        log.debug(f"Git repo access check failed: {code=} {stdout=} {stderr=}")
        return False
