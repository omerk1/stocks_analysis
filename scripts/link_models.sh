#!/usr/bin/env bash
# Symlink model/trial output directories from the main checkout into this
# checkout's data/models/, so a worktree can reuse trained outputs without
# copying them. Existing entries are reported and left alone.
#
# Usage:
#   bash scripts/link_models.sh <source_models_dir> <trial_id> [<trial_id> ...]
#
# <source_models_dir> must be an absolute path to the main checkout's
# data/models (checked after resolving symlinks and ".."; anything else is
# rejected). Trial IDs for an experiment:
#   python3 scripts/list_trial_ids.py S1
set -euo pipefail

usage() {
    echo "usage: bash scripts/link_models.sh <source_models_dir> <trial_id>..." >&2
    exit 2
}

[[ $# -ge 2 ]] || usage
src=${1%/}
shift

if [[ $src != /* ]]; then
    echo "error: source directory must be an absolute path: $src" >&2
    exit 2
fi
if [[ ! -d $src ]]; then
    echo "error: source directory not found: $src" >&2
    exit 1
fi

# Only the main checkout's data/models may be linked from. The main checkout
# is the parent of the git common dir; compare physical paths on both sides
# (cd -P follows each symlink before applying "..", as the filesystem does),
# and use the physical path from here on so no ".." reaches a link target.
main_checkout=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
if [[ ! -d $main_checkout/data/models ]]; then
    echo "error: main checkout has no data/models: $main_checkout/data/models" >&2
    exit 1
fi
allowed=$(cd -P "$main_checkout/data/models" && pwd -P)
resolved=$(cd -P "$src" && pwd -P)
if [[ $resolved != "$allowed" ]]; then
    echo "error: source must be $allowed" >&2
    exit 2
fi
src=$resolved

# Validate every ID before touching the filesystem.
for id in "$@"; do
    if [[ ! $id =~ ^[A-Za-z0-9_.-]+$ || $id == *..* || $id == . ]]; then
        echo "error: invalid trial id: '$id'" >&2
        exit 2
    fi
    if [[ ! -d $src/$id ]]; then
        echo "error: not found in source: $src/$id" >&2
        exit 1
    fi
done

cd "$(git rev-parse --show-toplevel)"
mkdir -p data/models

linked=0 already=0 conflicts=0
for id in "$@"; do
    dest=data/models/$id
    if [[ -L $dest && $(readlink "$dest") == "$src/$id" ]]; then
        echo "already linked: $dest"
        already=$((already + 1))
    elif [[ -e $dest || -L $dest ]]; then
        echo "skipped, exists and is not a link to $src/$id: $dest" >&2
        conflicts=$((conflicts + 1))
    else
        ln -s "$src/$id" "$dest"
        echo "linked: $dest -> $src/$id"
        linked=$((linked + 1))
    fi
done

echo "linked $linked, already linked $already, conflicts $conflicts"
[[ $conflicts -eq 0 ]]
