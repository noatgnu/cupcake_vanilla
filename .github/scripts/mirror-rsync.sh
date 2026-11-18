#!/bin/bash
# Copies SOURCE to DESTINATION on the download mirror with rsync over SSH. DESTINATION is relative
# to the mirror root, since the upload key is restricted to it by rrsync.
#
# Reads MIRROR_SSH_HOST, MIRROR_SSH_KEY and MIRROR_HOST_KEY, and optionally MIRROR_PORT, from the
# environment. Files arrive world-readable so the nginx container can serve them.
#
# SOURCE must be a folder: replacing a single file on the mirror fails, so files are uploaded inside a
# folder whose layout matches DESTINATION.
#
# Usage: mirror-rsync.sh <source folder>/ <destination folder>/
set -euo pipefail

SOURCE="${1:?source required}"
DESTINATION="${2:?destination required}"
if [ ! -d "$SOURCE" ]; then
    echo "mirror-rsync.sh: $SOURCE is not a folder; upload files inside a folder" >&2
    exit 2
fi
: "${MIRROR_SSH_HOST:?MIRROR_SSH_HOST required}"
: "${MIRROR_SSH_KEY:?MIRROR_SSH_KEY required}"
: "${MIRROR_HOST_KEY:?MIRROR_HOST_KEY required}"
PORT="${MIRROR_PORT:-22}"

KEY_FILE=$(mktemp)
KNOWN_HOSTS=$(mktemp)
trap 'rm -f "$KEY_FILE" "$KNOWN_HOSTS"' EXIT

printf '%s\n' "$MIRROR_SSH_KEY" > "$KEY_FILE"
chmod 600 "$KEY_FILE"
if [ "$PORT" = 22 ]; then KNOWN="$MIRROR_SSH_HOST"; else KNOWN="[$MIRROR_SSH_HOST]:$PORT"; fi
printf '%s %s\n' "$KNOWN" "$MIRROR_HOST_KEY" > "$KNOWN_HOSTS"

rsync -rt --partial --chmod=D755,F644 \
    -e "ssh -i $KEY_FILE -p $PORT -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KNOWN_HOSTS" \
    "$SOURCE" "mirror@${MIRROR_SSH_HOST}:${DESTINATION}"
