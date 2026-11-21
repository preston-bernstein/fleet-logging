#!/usr/bin/env bash
# Install the pinned tools the gates need, outside the repo, and print the PATH line to use them.
#
#   bash scripts/install-gate-tools.sh [TOOLS_DIR]     (default: $HOME/.cache/fleet-logging-gate-tools)
#
# lizard and zizmor come from a hash-locked file. jscpd comes from package-lock.json. vale and actionlint are
# release tarballs checked against a SHA-256 written here. To upgrade a tool, change its pin, regenerate its lock
# (`uv pip compile --generate-hashes`, `npm install --package-lock-only`) or its SHA-256, and read the diff.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="${1:-${GATE_TOOLS_DIR:-$HOME/.cache/fleet-logging-gate-tools}}"
VALE_VERSION=3.27.0
VALE_SHA256=c80d62f6bce87b81843ac5b512a26e63213927b957adba0a64fc594570da2000
ACTIONLINT_VERSION=1.7.12
ACTIONLINT_SHA256=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8

fail() { echo "install-gate-tools: $*" >&2; exit 1; }
for tool in uv npm curl tar sha256sum; do
  command -v "$tool" >/dev/null 2>&1 || fail "missing tool: $tool"
done

mkdir -p "$TOOLS/bin"

uv venv -q --allow-existing "$TOOLS/venv"
uv pip install -q --python "$TOOLS/venv" --require-hashes -r "$REPO/ci/gate-tools/requirements.txt"
ln -sf "$TOOLS/venv/bin/lizard" "$TOOLS/venv/bin/zizmor" "$TOOLS/bin/"

npm ci --silent --ignore-scripts --prefix "$REPO/ci/gate-tools" --no-audit --no-fund
rm -rf "$TOOLS/node_modules"
mv "$REPO/ci/gate-tools/node_modules" "$TOOLS/node_modules"
ln -sf "$TOOLS/node_modules/.bin/jscpd" "$TOOLS/bin/jscpd"

# fetch_release URL SHA256 MEMBER: download, verify, then unpack MEMBER into the bin directory.
fetch_release() {
  local url="$1" sha="$2" member="$3"
  tmp="$(mktemp -d)" # global, not local: the EXIT trap runs after this function returns
  trap 'rm -rf "$tmp"' EXIT
  curl -fsSL "$url" -o "$tmp/release.tar.gz"
  echo "$sha  $tmp/release.tar.gz" | sha256sum -c --quiet - || fail "checksum mismatch for $url"
  tar -xzf "$tmp/release.tar.gz" -C "$TOOLS/bin" "$member"
  rm -rf "$tmp"
}
fetch_release "https://github.com/vale-cli/vale/releases/download/v${VALE_VERSION}/vale_${VALE_VERSION}_Linux_64-bit.tar.gz" \
  "$VALE_SHA256" vale
fetch_release "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_amd64.tar.gz" \
  "$ACTIONLINT_SHA256" actionlint

echo "install-gate-tools: done. Run: export PATH=\"$TOOLS/bin:\$PATH\""
if [ -n "${GITHUB_PATH:-}" ]; then echo "$TOOLS/bin" >> "$GITHUB_PATH"; fi
