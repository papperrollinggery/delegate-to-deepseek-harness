#!/usr/bin/env bash
# Install the current checkout as a global Codex Skill.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
install_dir="${CODEX_HOME:-${HOME}/.codex}/skills/delegate-to-deepseek-harness"

command -v rsync >/dev/null 2>&1 || {
  echo "rsync is required" >&2
  exit 1
}

mkdir -p "${install_dir}/agents" "${install_dir}/scripts"
rsync -a "${root}/VERSION" "${install_dir}/VERSION"
rsync -a "${root}/SKILL.md" "${install_dir}/SKILL.md"
rsync -a "${root}/agents/openai.yaml" "${install_dir}/agents/openai.yaml"
for script in dsh_harness.py check-update.sh install-global.sh update-global.sh; do
  rsync -a "${root}/scripts/${script}" "${install_dir}/scripts/${script}"
  chmod 755 "${install_dir}/scripts/${script}"
done

echo "Installed delegate-to-deepseek-harness v$(tr -d '[:space:]' < "${root}/VERSION") at ${install_dir}"
