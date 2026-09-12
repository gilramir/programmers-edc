#!/bin/bash
# Export gren-tvision/ to gilramir/gren-tvision, where it is a repository of
# its own -- which is the only thing a Gren package can be. There is no
# registry to upload to: `gren package install gilramir/gren-tvision` reads
# that repository's tags and clones one, so its root has to be this directory.
#
#     tools/export-gren-tvision.sh          # push main
#     tools/export-gren-tvision.sh --tag    # ...and tag it, from gren.json
#     tools/export-gren-tvision.sh --dry-run
#
# The master copy is here. The export is one-directional and nothing is ever
# committed to it by hand. docs/publishing.md has the reasoning; this is the
# procedure.
#
# `git subtree split` is deterministic -- the same history always produces the
# same commits -- so a second export is a fast-forward carrying only what has
# changed, and only commits that touched this directory become commits there.
# What breaks that is amending or rebasing a commit that has already gone out:
# its split commit gets a different hash, everything after it is orphaned, and
# the push is rejected. Never rewrite a commit that has been exported.
#
# Only `split` is used. `git subtree add`/`pull`/`push` want the remote in this
# repository's history and make merge commits here; this touches nothing.
set -euo pipefail

cd "$(dirname "$0")/.."

PREFIX=gren-tvision
REMOTE=gren-tvision
URL=git@github.com:gilramir/gren-tvision.git

tag=""
dry=""
for arg in "$@"; do
    case "$arg" in
        --tag) tag=yes ;;
        --dry-run) dry=yes ;;
        *) echo "usage: $0 [--tag] [--dry-run]" >&2; exit 2 ;;
    esac
done

die() { echo "$*" >&2; exit 1; }

# ---------------------------------------------------------------- the remote

if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
    die "no '$REMOTE' remote. Add it with:
    git remote add $REMOTE $URL
It is four lines in .git/config and no files on disk -- the export is pushed
straight from here and never checked out."
fi

# ------------------------------------------------------------ what to export

# The split is of committed history, so a dirty tree means what goes out is not
# what is on screen. That is the kind of thing nobody notices until a consumer
# reports a bug against code that was never released.
if [ -n "$(git status --porcelain)" ]; then
    die "the working tree is dirty. Commit first -- the export is of committed
history, so anything uncommitted would silently not go."
fi

# The version is a property of the *tag* and of nothing else, so an untagged
# export does not read it, check it or mention it -- naming a version while
# pushing a branch reads as a release, and this is not one.
if [ -n "$tag" ]; then
    # Read rather than typed: two places saying a version number is one too
    # many, and `gren package bump` moves this one.
    version=$(python3 -c "import json;print(json.load(open('$PREFIX/gren.json'))['version'])")

    # A tag gren cannot parse is not an error to gren -- Git.gren drops it with
    # mapAndKeepJust and the package simply has no such version. So check the
    # shape here, where somebody is watching. SemanticVersion.fromString splits
    # on "." and wants exactly three integers: no leading v, no -beta.
    if ! [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        die "'$version' in $PREFIX/gren.json is not a version gren can read.
It splits on '.' and wants exactly three integers -- no leading v, no suffix."
    fi

    if git ls-remote --tags "$REMOTE" "refs/tags/$version" | grep -q .; then
        die "$version is already tagged on $REMOTE. Bump the version in
$PREFIX/gren.json -- \`cd $PREFIX && gren package bump\` works it out from the
published docs -- or drop --tag to push main without releasing."
    fi

    echo "exporting $PREFIX/ as $version"
else
    echo "exporting $PREFIX/ -- branch only, no tag"
fi

# ----------------------------------------------------------------- the split

sha=$(git subtree split --prefix="$PREFIX" 2>/dev/null | tail -1)
[ -n "$sha" ] || die "git subtree split produced nothing"

count=$(git rev-list --count "$sha")
echo "  split:  $sha  ($count commits)"

# What is already up there, so the summary can say what this adds -- and so a
# rewrite is explained here rather than by git's fast-forward hint.
remote_head=$(git ls-remote "$REMOTE" refs/heads/main | cut -f1)
if [ -z "$remote_head" ]; then
    echo "  remote: empty, this is the first export"
elif [ "$remote_head" = "$sha" ]; then
    echo "  remote: already at this commit, nothing to push"
elif git merge-base --is-ancestor "$remote_head" "$sha" 2>/dev/null; then
    echo "  adding: $(git rev-list --count "$remote_head..$sha") commits"
else
    die "the export has moved out from under this one.
$REMOTE is at $remote_head, which is not an ancestor of $sha.
Either somebody committed to the export by hand -- nobody should -- or a
commit that had already been exported was amended or rebased here. See
docs/publishing.md."
fi

# ------------------------------------------------------------------ the push

refs=("$sha:refs/heads/main")
[ -n "$tag" ] && refs+=("$sha:refs/tags/$version")

if [ -n "$dry" ]; then
    echo "  would: git push $REMOTE ${refs[*]}"
    exit 0
fi

# Both refs in one command, so a tag without its branch is not a state this can
# reach.
git push "$REMOTE" "${refs[@]}"

echo
if [ -n "$tag" ]; then
    echo "released $version. Check it with:"
    echo "    (cd $PREFIX && gren package validate)"
    echo "and consider tagging this repository too -- a split commit carries no"
    echo "record of where it came from, so nothing otherwise says which commit"
    echo "here produced it:"
    echo "    git tag $PREFIX/$version && git push origin $PREFIX/$version"
else
    echo "pushed main, untagged. Nothing depends on it until a semver tag does:"
    echo "    $0 --tag"
fi
