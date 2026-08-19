#!/usr/bin/env bash
# Quiet daily update check for the installed delegate-to-deepseek-harness Skill.
set -u

SKILL="delegate-to-deepseek-harness"
REPO="papperrollinggery/delegate-to-deepseek-harness"
REMOTE_URL="${DSH_UPDATE_URL:-https://api.github.com/repos/${REPO}/releases/latest}"

[ "${DSH_DISABLE_UPDATE_CHECK:-0}" != "1" ] || exit 0
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
local_ver="$(tr -d '[:space:]' < "${root}/VERSION" 2>/dev/null)"
[ -n "${local_ver}" ] || exit 0

day="$(date +%F 2>/dev/null)" || exit 0
cache_base="${XDG_CACHE_HOME:-${HOME:-}}"
[ -n "${cache_base}" ] || exit 0
[ -n "${XDG_CACHE_HOME:-}" ] || cache_base="${cache_base}/.cache"
cache_dir="${cache_base}/${SKILL}"
marker="${cache_dir}/update-checked"
[ "$(cat "${marker}" 2>/dev/null)" != "${day}" ] || exit 0
mkdir -p "${cache_dir}" 2>/dev/null
printf '%s' "${day}" > "${marker}" 2>/dev/null

command -v curl >/dev/null 2>&1 || exit 0
remote_payload="$(curl -fsSL --max-time 3 "${REMOTE_URL}" 2>/dev/null)"
remote_ver="$(printf '%s\n' "${remote_payload}" | sed -nE 's/.*"tag_name":[[:space:]]*"v([0-9]+\.[0-9]+\.[0-9]+)".*/\1/p' | head -1)"
[ -n "${remote_ver}" ] || remote_ver="$(printf '%s' "${remote_payload}" | tr -d '[:space:]')"
[[ "${remote_ver}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 0
[ "${remote_ver}" != "${local_ver}" ] || exit 0

highest="$(printf '%s\n%s\n' "${local_ver}" "${remote_ver}" | sort -t. -k1,1n -k2,2n -k3,3n 2>/dev/null | tail -1)"
[ "${highest}" = "${remote_ver}" ] || exit 0

echo "delegate-to-deepseek-harness v${remote_ver} is available (installed v${local_ver}). Ask the user whether to update; after approval run: bash scripts/update-global.sh"
