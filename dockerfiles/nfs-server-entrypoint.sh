#!/bin/sh
set -eu

EXPORT_DIR="${NFS_EXPORT_DIR:-/export}"
EXPORT_OPTIONS="${NFS_EXPORT_OPTIONS:-ro,fsid=0,no_subtree_check,insecure,no_root_squash}"

mkdir -p "$EXPORT_DIR" /var/lib/nfs/v4recovery
echo "$EXPORT_DIR *($EXPORT_OPTIONS)" > /etc/exports

if ! mountpoint -q /proc/fs/nfsd; then
    mount -t nfsd nfsd /proc/fs/nfsd
fi

exportfs -ra
rpc.nfsd --no-nfs-version 3 --nfs-version 4 --no-udp "${NFS_THREADS:-8}"
echo "Serving $EXPORT_DIR over NFSv4 ($EXPORT_OPTIONS)"

stop() {
    rpc.nfsd 0
    exportfs -ua
    exit 0
}
trap stop TERM INT

rpc.mountd --no-nfs-version 2 --no-nfs-version 3 --no-udp --foreground &
wait $!
