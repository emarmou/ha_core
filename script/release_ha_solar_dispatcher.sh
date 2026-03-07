#!/usr/bin/env bash
# Release ha_solar_dispatcher to the HACS integration repository.
#
# Usage:
#   ./script/release_ha_solar_dispatcher.sh [--version <x.y.z>] [--hacs-repo <path>]
#
# Options:
#   --version   Version to set in manifest.json (e.g. 1.2.0). Defaults to
#               the current version in manifest.json.
#   --hacs-repo Path to a local clone of the HACS repo. Defaults to
#               ../hacs-ha-solar-dispatcher (sibling of this repo).
#
# Example:
#   ./script/release_ha_solar_dispatcher.sh --version 1.0.3

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SRC="${REPO_ROOT}/homeassistant/components/ha_solar_dispatcher"
HACS_REPO="${REPO_ROOT}/../hacs_solar_dispatcher"
NEW_VERSION=""

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      NEW_VERSION="$2"
      shift 2
      ;;
    --hacs-repo)
      HACS_REPO="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Validate environment
# ---------------------------------------------------------------------------
if [[ ! -d "${SRC}" ]]; then
  echo "ERROR: Source integration not found at ${SRC}"
  exit 1
fi

if [[ ! -d "${HACS_REPO}" ]]; then
  echo "ERROR: HACS repo not found at ${HACS_REPO}"
  echo "  Clone it first:  git clone <your-hacs-repo-url> ${HACS_REPO}"
  exit 1
fi

DST="${HACS_REPO}/custom_components/ha_solar_dispatcher"
mkdir -p "${DST}"

# ---------------------------------------------------------------------------
# Copy integration files (exclude dev-only files)
# ---------------------------------------------------------------------------
echo "Copying integration files..."
rsync -a --delete \
  --exclude="__pycache__/" \
  --exclude="*.pyc" \
  --exclude="quality_scale.yaml" \
  "${SRC}/" "${DST}/"

echo "  → ${DST}"

# ---------------------------------------------------------------------------
# Optional: bump version in manifest.json
# ---------------------------------------------------------------------------
MANIFEST="${DST}/manifest.json"

if [[ -n "${NEW_VERSION}" ]]; then
  if command -v python3 &>/dev/null; then
    python3 - "${MANIFEST}" "${NEW_VERSION}" <<'EOF'
import json, sys

path, version = sys.argv[1], sys.argv[2]
with open(path) as f:
    data = json.load(f)
data["version"] = version
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
EOF
    echo "  Version set to ${NEW_VERSION} in manifest.json"
  else
    echo "WARNING: python3 not found – version not updated in manifest.json"
  fi
else
  CURRENT_VERSION=$(python3 -c "import json; print(json.load(open('${MANIFEST}')).get('version','unset'))")
  echo "  Keeping existing version: ${CURRENT_VERSION}"
  NEW_VERSION="${CURRENT_VERSION}"
fi

# ---------------------------------------------------------------------------
# Commit and tag in HACS repo
# ---------------------------------------------------------------------------
cd "${HACS_REPO}"

# Abort early if this version was already released (tag already exists).
TAG="v${NEW_VERSION}"
if git rev-parse "${TAG}" &>/dev/null; then
  echo "ERROR: Tag ${TAG} already exists in the HACS repo."
  echo "  Bump the version with --version <x.y.z> before releasing again."
  exit 1
fi

# Use git status --porcelain so new/untracked files are also detected.
STATUS=$(git status --porcelain custom_components/ha_solar_dispatcher/)
if [[ -n "${STATUS}" ]]; then
  echo ""
  echo "Changes detected in HACS repo. Committing..."
  git add custom_components/ha_solar_dispatcher/
  git commit -m "Release v${NEW_VERSION}"
  echo "  Committed: Release v${NEW_VERSION}"
else
  echo ""
  echo "No changes detected – HACS repo already up to date."
  exit 0
fi

# Create a git tag (required by HACS for versioned releases).
git tag "${TAG}"
echo "  Tagged: ${TAG}"

echo ""
echo "Done! To publish, run:"
echo "  cd ${HACS_REPO} && git push origin master --tags"
