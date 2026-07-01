[![Python checks](https://github.com/linkFISH-Consulting/coasti_installer/actions/workflows/python.yml/badge.svg?branch=main)](https://github.com/linkFISH-Consulting/coasti_installer/actions/workflows/python.yml)
[![PyPI - Version](https://img.shields.io/pypi/v/coasti)](https://pypi.org/project/coasti/)
[![Documentation](https://app.readthedocs.org/projects/coasti/badge/?version=latest&style=flat)](https://coasti.readthedocs.io/en/latest/)
[![Copier](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/copier-org/copier/master/img/badge/badge-grayscale-inverted-border-orange.json)](https://github.com/copier-org/copier)

# Coasti installer

## Get started

Install [uv](https://docs.astral.sh/uv/getting-started/installation/)

```bash
# macOS, Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Get the coasti installer. More details on uv install methods [here](https://docs.astral.sh/uv/getting-started/features/#tools)

```bash
# as tool, global cli, creates an isolated environment
uv tool install coasti

# as package, installes into the current environment
uv pip install coasti
```

Create a coasti project and install products

```bash
coasti init my_coasti_project
cd my_coasti_project

coasti product add "https://github.com/my_product_repo.git"
```

## Further reading

- [Changelog](https://github.com/linkFISH-Consulting/coasti_installer/CHANGELOG.md)
- [Docs](https://github.com/linkFISH-Consulting/coasti_installer/docs)
    - [installer specs](https://github.com/linkFISH-Consulting/coasti_installer/docs/installer_specs.md)
    - [contributing](https://github.com/linkFISH-Consulting/coasti_installer/docs/contribution_guide.md)
    - [list of environment variables](https://github.com/linkFISH-Consulting/coasti_installer/docs/env_vars.md)
    - [dev container](https://github.com/linkFISH-Consulting/coasti_installer/docker/README.md)
