#!/usr/bin/env bash
# Update the global Codex Skill from the latest published GitHub release.
# Run only after the user explicitly approves the available update.
set -euo pipefail

REPO="papperrollinggery/delegate-to-deepseek-harness"
VERSION_URL="${DSH_UPDATE_URL:-https://api.github.com/repos/${REPO}/releases/latest}"

command -v curl >/dev/null 2>&1 || {
  echo "curl is required" >&2
  exit 1
}
command -v tar >/dev/null 2>&1 || {
  echo "tar is required" >&2
  exit 1
}

release_payload="$(curl -fsSL --max-time 10 "${VERSION_URL}")"
latest="$(printf '%s\n' "${release_payload}" | sed -nE 's/.*"tag_name":[[:space:]]*"v([0-9]+\.[0-9]+\.[0-9]+)".*/\1/p' | head -1)"
[ -n "${latest}" ] || latest="$(printf '%s' "${release_payload}" | tr -d '[:space:]')"
[[ "${latest}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "Invalid release version: ${latest}" >&2
  exit 1
}
archive_url="${DSH_UPDATE_ARCHIVE_URL:-https://github.com/${REPO}/archive/refs/tags/v${latest}.tar.gz}"
work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT

curl -fsSL --max-time 60 "${archive_url}" -o "${work_dir}/release.tar.gz"
mkdir -p "${work_dir}/release"
tar -xzf "${work_dir}/release.tar.gz" -C "${work_dir}/release" --strip-components=1
[ "$(tr -d '[:space:]' < "${work_dir}/release/VERSION")" = "${latest}" ] || {
  echo "Release archive version does not match v${latest}" >&2
  exit 1
}
bash "${work_dir}/release/scripts/install-global.sh"
