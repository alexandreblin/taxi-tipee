#!/usr/bin/env bash
#
# Usage: ./release.sh VERSION
#
# Bumps the version, builds and checks the distributions, then commits, tags
# and pushes. The tag triggers .github/workflows/release.yml, which builds
# them again and uploads them to PyPI as a trusted publisher: no API token.
#
# The tools come from the flake's dev shell. Run this from `nix develop` (or
# direnv), or let it re-execute itself there.
set -euo pipefail

cd "$(dirname "$0")"

if [ -z "${TAXI_TIPEE_DEVSHELL:-}" ]; then
    exec nix develop --command "$0" "$@"
fi

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 VERSION" >&2
    exit 1
fi
version=$1

if [ "$(git branch --show-current)" != master ]; then
    echo "Not on master." >&2
    exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
    echo "The working tree is not clean." >&2
    exit 1
fi
git fetch --quiet origin master
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/master)" ]; then
    echo "master is not up to date with origin/master." >&2
    exit 1
fi
if git rev-parse --quiet --verify "refs/tags/$version" >/dev/null; then
    echo "Tag $version already exists." >&2
    exit 1
fi

read -r -p "Are you sure you want to release version '$version'? [y/n] " yn
case $yn in
    [Yy]*) ;;
    *) exit ;;
esac

echo "__version__ = '$version'" > taxi_tipee/__init__.py

# Build before committing, so a broken build leaves nothing pushed.
rm -rf dist build taxi_tipee.egg-info
python -m build --no-isolation
twine check dist/*

git commit -m "Bump version number to $version" taxi_tipee/__init__.py
# Sign the tag when git has a signing key; annotate it either way.
if git config --get user.signingkey >/dev/null; then
    git tag -s -m "Release $version" "$version"
else
    git tag -a -m "Release $version" "$version"
fi
git push origin master "$version"

echo "Pushed $version; GitHub Actions publishes it to PyPI:"
echo "  https://github.com/alexandreblin/taxi-tipee/actions/workflows/release.yml"
