# Contributing

## Build and upload to pypi

- Add a git tag with the current version number, otherwise the build template will not be versioned!

```bash

# 0) create a tag on your local git repo (needed for copier versioning)
# this is a manual step for now

# 1) create the git template bundle to ship
python ./src/coasti/create_template_bundle.py

# 2) build the package
uv build

# 3) publish

# publish on pypi test
export UV_PUBLISH_TOKEN="pypi-XXXXXXXXXXXXXXXXXXXXXXXX"
uv publish --index-url https://test.pypi.org/legacy/

# test it works
uv pip install --index-url https://test.pypi.org/simple/ --no-deps coasti

# final publish to pypi
export UV_PUBLISH_TOKEN="pypi-XXXXXXXXXXXXXXXXXXXXXXXX"
uv publish
```
