#!/usr/bin/env bash
# Backs up (or restores) the named volumes that hold this stack's user
# data: Open WebUI accounts/chats, agent artifacts, and Isabelle theory
# files. Each volume is written to its own .tar.zst archive so a single
# volume can be restored without touching the others.
set -euo pipefail

ENGINE="${CONTAINER_ENGINE:-docker}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-dist}"
VOLUMES=(webui-data agent-data isabelle-workspace)

usage() {
  cat <<EOF
Usage:
  $(basename "$0") backup [BACKUP_DIR]
  $(basename "$0") restore ARCHIVE VOLUME_NAME

backup   Writes one <volume>-<timestamp>.tar.zst per volume into BACKUP_DIR
         (default: ./volume-backups).
restore  Restores a single archive into VOLUME_NAME (created if missing).
         Files from the archive overwrite same-named files already there.

Volumes covered (with the "${PROJECT_NAME}_" compose project prefix):
$(printf '  %s\n' "${VOLUMES[@]/#/${PROJECT_NAME}_}")

Env overrides:
  CONTAINER_ENGINE     docker (default) or podman
  COMPOSE_PROJECT_NAME compose project prefix (default: dist)
EOF
}

require_zstd() {
  command -v zstd >/dev/null 2>&1 || {
    echo "error: 'zstd' not found on host (apt/pacman/brew install zstd)" >&2
    exit 1
  }
}

do_backup() {
  local out_dir="${1:-./volume-backups}"
  mkdir -p "$out_dir"
  local stamp
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  local archives=()
  for base in "${VOLUMES[@]}"; do
    local vol="${PROJECT_NAME}_${base}"
    local archive="$out_dir/${base}-${stamp}.tar.zst"
    echo "backing up $vol -> $archive"
    "$ENGINE" run --rm -v "${vol}:/vol:ro" alpine tar cf - -C / vol \
      | zstd -q -T0 -o "$archive"
    archives+=("$archive:$vol")
  done
  echo
  echo "Done. To restore a volume from one of these archives:"
  for entry in "${archives[@]}"; do
    echo "  $0 restore ${entry%%:*} ${entry##*:}"
  done
}

do_restore() {
  local archive="$1" vol="$2"
  [[ -f "$archive" ]] || { echo "error: no such archive: $archive" >&2; exit 1; }
  echo "restoring $archive -> volume $vol"
  "$ENGINE" volume create "$vol" >/dev/null
  zstd -dc "$archive" | "$ENGINE" run --rm -i -v "${vol}:/vol" alpine tar xf - -C /
  echo "done."
}

case "${1:-}" in
  backup)
    require_zstd
    do_backup "${2:-}"
    ;;
  restore)
    require_zstd
    [[ $# -eq 3 ]] || { usage; exit 1; }
    do_restore "$2" "$3"
    ;;
  *)
    usage
    exit 1
    ;;
esac
