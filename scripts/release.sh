#!/usr/bin/env bash
#
# Release script for the Annotated Grateful Dead Lyrics mirror.
#
# Git tags are the source of truth for versions. This script determines the
# next semantic version from Conventional Commits since the last v* tag,
# previews the changelog, then creates and pushes an annotated tag vX.Y.Z.
# Pushing the tag triggers .github/workflows/release.yml, which builds the
# site, attaches dist.zip, and publishes a GitHub Release.
#
# It deliberately does NOT commit to main (main is PR-protected) — the tag is
# all that is needed.
#
# Usage:
#   scripts/release.sh                 # auto version from commits, create+push tag
#   scripts/release.sh 1.2.3           # explicit version
#   scripts/release.sh --dry-run       # preview only, no tag created/pushed
#   scripts/release.sh --notes vX.Y.Z  # print release notes for a tag to stdout
#                                       # (used by the release workflow)
#
# Version bump rules (Conventional Commits since the last tag):
#   feat!: / fix!: / BREAKING CHANGE  -> major
#   feat:                             -> minor
#   fix: / perf:                      -> patch
#
set -euo pipefail

GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'

# Print one changelog section (heading + bullets) for commits in $range matching
# $pattern. Emits nothing if there are no matching commits.
_section() {
  local range=$1 pattern=$2 title=$3 lines
  lines=$(git log $range --pretty=format:'%s (%h)' | grep -E "$pattern" \
          | sed -E 's/^[a-z]+(\([^)]+\))?!?: //' || true)
  if [ -n "$lines" ]; then
    printf '### %s\n' "$title"
    printf '%s\n' "$lines" | sed 's/^/- /'
    printf '\n'
  fi
}

# Build the full changelog (plain Markdown) for $tag over commit $range.
build_changelog() {
  local tag=$1 range=$2
  printf '## %s — %s\n\n' "$tag" "$(date +%Y-%m-%d)"
  _section "$range" '^feat(\([^)]+\))?!?:' 'Features'
  _section "$range" '^fix(\([^)]+\))?!?:'  'Fixes'
  _section "$range" '^perf(\([^)]+\))?:'   'Performance'
}

# Commit range from the tag before $tag up to $tag (empty if it's the first).
range_before_tag() {
  local tag=$1 prev
  prev=$(git describe --tags --abbrev=0 "${tag}^" --match 'v*' 2>/dev/null || echo "")
  [ -n "$prev" ] && echo "${prev}..${tag}" || echo ""
}

# --- --notes mode: print notes for an existing tag and exit (used by CI) ------
if [ "${1:-}" = "--notes" ]; then
  [ -n "${2:-}" ] || { echo "usage: $0 --notes vX.Y.Z" >&2; exit 2; }
  build_changelog "$2" "$(range_before_tag "$2")"
  exit 0
fi

DRY_RUN=false
VERSION=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    -h|--help) sed -n '2,33p' "$0"; exit 0 ;;
    *) VERSION="$arg" ;;
  esac
done

echo -e "${BLUE}🌹 Annotated GD Lyrics — release${NC}"

LAST_TAG=$(git describe --tags --abbrev=0 --match 'v*' 2>/dev/null || echo "")
if [ -z "$LAST_TAG" ]; then
  RANGE=""
  echo -e "${YELLOW}No previous tag — this is the first release.${NC}"
else
  RANGE="${LAST_TAG}..HEAD"
  echo -e "${BLUE}Last tag: ${LAST_TAG}${NC}"
fi

if [ -n "$VERSION" ]; then
  echo -e "${BLUE}Using explicit version: ${VERSION}${NC}"
elif [ -z "$LAST_TAG" ]; then
  VERSION="0.1.0"
  echo -e "${BLUE}Defaulting first release to ${VERSION}${NC}"
else
  base=${LAST_TAG#v}
  IFS='.' read -r MAJOR MINOR PATCH <<< "${base%%[-+]*}"

  subjects=$(git log "$RANGE" --pretty=format:'%s')
  bodies=$(git log "$RANGE" --pretty=format:'%B')
  feat_break=$(printf '%s\n' "$subjects" | grep -cE '^[a-z]+(\([^)]+\))?!:' || true)
  body_break=$(printf '%s\n' "$bodies"   | grep -cE 'BREAKING CHANGE' || true)
  feats=$(printf '%s\n' "$subjects" | grep -cE '^feat(\([^)]+\))?:' || true)
  fixes=$(printf '%s\n' "$subjects" | grep -cE '^(fix|perf)(\([^)]+\))?:' || true)

  echo -e "${BLUE}Since ${LAST_TAG}: ${feat_break}+${body_break} breaking, ${feats} feat, ${fixes} fix/perf${NC}"

  if [ $((feat_break + body_break)) -gt 0 ]; then
    MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0
  elif [ "$feats" -gt 0 ]; then
    MINOR=$((MINOR + 1)); PATCH=0
  elif [ "$fixes" -gt 0 ]; then
    PATCH=$((PATCH + 1))
  else
    echo -e "${RED}No user-facing changes (feat/fix/perf) since ${LAST_TAG}. Nothing to release.${NC}"
    exit 1
  fi
  VERSION="${MAJOR}.${MINOR}.${PATCH}"
  echo -e "${GREEN}Next version: ${VERSION}${NC}"
fi

if ! [[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$ ]]; then
  echo -e "${RED}Invalid version '${VERSION}' (expected semver like 1.2.3).${NC}"; exit 1
fi
TAG="v${VERSION}"
if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo -e "${RED}Tag ${TAG} already exists.${NC}"; exit 1
fi

CHANGELOG=$(build_changelog "$TAG" "$RANGE")

echo ""
echo -e "${BLUE}Changelog preview:${NC}"
echo "-------------------------------------"
printf '%s\n' "$CHANGELOG"
echo "-------------------------------------"

if [ "$DRY_RUN" = true ]; then
  echo -e "${YELLOW}DRY RUN — would create and push tag ${TAG}. No changes made.${NC}"
  exit 0
fi

echo -e "${GREEN}Creating tag ${TAG}…${NC}"
# --cleanup=verbatim so Markdown '#' headings in the changelog are not stripped.
git tag -a "$TAG" --cleanup=verbatim -m "$CHANGELOG"
git push origin "$TAG"
echo -e "${GREEN}Pushed ${TAG}. The release workflow will build the site and publish the GitHub Release.${NC}"
