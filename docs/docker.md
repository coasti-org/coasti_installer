# Dev Container to test the installer

Main aim is to get a clean environment without your usual git setup in place.

```
docker compose -f ./docker/docker-compose.yml build
docker run --rm -it -v ./:/app docker-coasti-installer bash

export UV_PROJECT_ENVIRONMENT=/.venv
uv sync --all-extras --all-groups --link-mode copy
source /.venv/bin/activate

coasti --help
```
