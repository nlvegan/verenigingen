#!/bin/bash
# Run a command with this repo's node_modules resolvable.
#
# node_modules is gitignored, so it is absent from every git worktree - and worktrees are
# how branch work is done here, because bench serves the live site straight out of the
# main checkout. Without this, npm-based hooks fail for a reason that has nothing to do
# with the diff, which teaches people to reach for SKIP= and switches off the checks that
# do matter.
#
# For npx-based hooks the stakes are higher than a failure: npx responds to a missing
# local install by downloading the package from the network, so eslint would silently run
# at whatever version it fetched rather than the one this repo pins. Putting the real
# node_modules/.bin on PATH is what stops that.
#
# Falls back to skipping with a message, rather than failing, when no install exists
# anywhere - a machine that has never run `npm install` should not be blocked from
# committing by every JS hook at once.

set -e

if [[ $# -eq 0 ]]; then
    echo "usage: with-node-modules.sh <command> [args...]" >&2
    exit 2
fi

if [[ -d "node_modules/.bin" ]]; then
    NODE_MODULES="$PWD/node_modules"
else
    MAIN_CHECKOUT=$(dirname "$(git rev-parse --git-common-dir 2>/dev/null || echo .)")
    if [[ -d "$MAIN_CHECKOUT/node_modules/.bin" ]]; then
        echo "ℹ️  No node_modules in this checkout - using $MAIN_CHECKOUT/node_modules"
        NODE_MODULES="$MAIN_CHECKOUT/node_modules"
    else
        echo "⏭️  Skipping '$1': node_modules is not installed. Run 'npm install' to enable it."
        exit 0
    fi
fi

# Put the resolved install on PATH unconditionally, including when it is the local one.
# Callers must invoke tools directly (`eslint`, not `npx eslint`): npx resolves a package
# from the *current directory's* node_modules and ignores PATH entirely, so under npx a
# worktree silently falls back to ~/.npm/_npx - which is how eslint 10.8.1 from the npx
# cache ended up loading eslint-plugin-vue from this repo's install and dying on
# `context.getSourceCode is not a function`. Running the binary directly pins both halves
# to the same tree.
export PATH="$NODE_MODULES/.bin:$PATH"
export NODE_PATH="$NODE_MODULES"

exec "$@"
