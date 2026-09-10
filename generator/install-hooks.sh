#!/bin/sh
# Point this clone's hooks at the ones tracked in the repository.
set -e
root="$(git rev-parse --show-toplevel)"
ln -sf ../../generator/hooks/pre-commit "$root/.git/hooks/pre-commit"
echo 'pre-commit hook installed (runs generator/build.py --check).'
