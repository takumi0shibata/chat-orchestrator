#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 [patch|minor|major]"
  exit 1
fi

BUMP_TYPE="$1"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VERSION_FILE="$ROOT_DIR/VERSION"
BACKEND_FILE="$ROOT_DIR/backend/pyproject.toml"
FRONTEND_FILE="$ROOT_DIR/frontend/package.json"

if [[ ! -f "$VERSION_FILE" ]]; then
  echo "VERSION file not found: $VERSION_FILE"
  exit 1
fi

OLD_VERSION="$(cat "$VERSION_FILE" | tr -d '[:space:]')"
IFS='.' read -r MAJOR MINOR PATCH <<< "$OLD_VERSION"

case "$BUMP_TYPE" in
  patch)
    PATCH=$((PATCH + 1))
    ;;
  minor)
    MINOR=$((MINOR + 1))
    PATCH=0
    ;;
  major)
    MAJOR=$((MAJOR + 1))
    MINOR=0
    PATCH=0
    ;;
  *)
    echo "Invalid bump type: $BUMP_TYPE"
    exit 1
    ;;
esac

NEW_VERSION="$MAJOR.$MINOR.$PATCH"

echo "$NEW_VERSION" > "$VERSION_FILE"

awk -v v="$NEW_VERSION" '
  /^version = "/ { sub(/"[0-9]+\.[0-9]+\.[0-9]+"/, "\"" v "\"") }
  { print }
' "$BACKEND_FILE" > "$BACKEND_FILE.tmp" && mv "$BACKEND_FILE.tmp" "$BACKEND_FILE"

awk -v v="$NEW_VERSION" '
  /"version": "/ { sub(/"[0-9]+\.[0-9]+\.[0-9]+"/, "\"" v "\"") }
  { print }
' "$FRONTEND_FILE" > "$FRONTEND_FILE.tmp" && mv "$FRONTEND_FILE.tmp" "$FRONTEND_FILE"

TODAY="$(date +%Y-%m-%d)"
awk -v v="$NEW_VERSION" -v d="$TODAY" '
  BEGIN { inserted = 0 }
  {
    print $0
    if ($0 == "## [Unreleased]" && inserted == 0) {
      print ""
      print "## [" v "] - " d
      print ""
      print "### Added"
      print "- "
      print ""
      print "### Changed"
      print "- "
      print ""
      print "### Fixed"
      print "- "
      inserted = 1
    }
  }
' "$ROOT_DIR/CHANGELOG.md" > "$ROOT_DIR/CHANGELOG.md.tmp" && mv "$ROOT_DIR/CHANGELOG.md.tmp" "$ROOT_DIR/CHANGELOG.md"

echo "Version bumped: $OLD_VERSION -> $NEW_VERSION"
echo "Next steps:"
echo "  1) Update CHANGELOG.md section [$NEW_VERSION]"
echo "  2) git add VERSION backend/pyproject.toml frontend/package.json CHANGELOG.md"
echo "  3) git commit -m \"chore(release): v$NEW_VERSION\""
echo "  4) git tag v$NEW_VERSION"
echo "  5) git push origin main --tags"
