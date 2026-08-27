from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from coasti.prompt import QuestionsDict


class ProductData(TypedDict):
    """
    Answers to product-specific questions,

    which will end up in config/products.yml
    """

    # see questions/copier.yml
    vcs_repo: str
    id: str
    dst_path: str
    vcs_ref: str
    vcs_auth_type: Literal["skip", "Auth Token", "SSH Key"]
    vcs_auth_value: str

    # helper questions
    vcs_auth_token: NotRequired[str]
    vcs_auth_sshkeypath: NotRequired[str]

    # depending on type, either path to an ssh key pair, or a token.
    # senintal value: "__file__"

    # installed_at: datetime
    # last_updated_at: datetime


# placeholders in products.yml for vcs_auth_value
AUTH_FILE_SENTINEL = "__file__"  # get secret from file
AUTH_SKIP_SENTINEL = "__skip__"  # when no auth used

PRODUCT_QUESTIONS: QuestionsDict = {
    "vcs_repo": {"type": "str", "help": "Url of the product's git repo"},
    # ask for authentication first, to check connection
    "vcs_auth_type": {
        "type": "str",
        "help": "How to authenticateq at {{ vcs_repo }}",
        "choices": ["skip", "Auth Token", "SSH Key"],
        "default": "skip",
    },
    # two helper questions for vcs_auth_value
    "vcs_auth_token": {
        "type": "str",
        "help": "Enter your auth token:",
        "placeholder": "github_pat_123...",
        "default": "",
        "secret": True,
        "when": "{{ vcs_auth_type in ['Auth Token'] }}",
    },
    "vcs_auth_sshkeypath": {
        "type": "str",
        "help": "Enter an absolute path to an ssh key-pair:",
        "placeholder": "{{ '~/.ssh/id_rsa' | expanduser }}",
        "default": "{{ '~/.ssh/id_rsa' | expanduser }}",
        "when": "{{ vcs_auth_type in ['SSH Key'] }}",
    },
    "vcs_auth_value": {
        "default": (
            "{%- if vcs_auth_type == 'Auth Token' -%}{{ vcs_auth_token }}"
            "{%- elif vcs_auth_type == 'SSH Key' -%}{{ vcs_auth_sshkeypath }}"
            "{%- else -%}" + AUTH_SKIP_SENTINEL + "{%- endif -%}"
        ),
        "secret": True,
        "when": False,
    },
    # Fixme: id should come from a custom coasti.yml (or copier.yml?)
    "id": {
        "type": "str",
        "help": "Unique Product identifier:",
        # strip everything up to the last "/", then a trailing ".git"
        "default": (
            "{{ vcs_repo | regex_replace('^.*/', '') | regex_replace('\\.git$', '') }}"
        ),
    },
    "dst_path": {
        "type": "str",
        "help": "Install location:",
        "default": "products/{{ id }}",
    },
    "vcs_ref": {
        "type": "str",
        "help": "Version control reference (git branch, tag or commit)",
        "default": "main",
    },
}
