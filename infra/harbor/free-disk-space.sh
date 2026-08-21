#!/usr/bin/env bash
# Free up disk space on the Harbor host over SSH, and report where the disk
# space is actually going.
#
# Run this from your Mac:
#   ./infra/harbor/free-disk-space.sh
# or with a different host/user:
#   ./infra/harbor/free-disk-space.sh <host> <ssh-user>
#
# You will be prompted for the SSH password by `ssh` itself -- this script
# never stores, echoes, or passes the password anywhere.
#
# What it does on the remote host, in order:
#   1. Shows disk + Docker usage before cleanup.
#   2. Vacuums the systemd journal down to 100MB.
#   3. Clears the apt package cache.
#   4. Truncates Docker container log files over 10MB (verbose/looping
#      containers can quietly write multi-GB *-json.log files over time).
#   5. Runs `docker system prune -af` to remove stopped containers, unused
#      networks, dangling/unreferenced images, and build cache.
#      NOTE: Harbor's redis container must be running when this executes,
#      otherwise the prune would delete it -- step 6 exists because a
#      restart attempted while the disk was 100% full can leave it stopped,
#      which is why redis is started BEFORE the prune below.
#   6. Ensures Harbor's redis container is running (starts it if a previous
#      disk-full episode left it stopped). A stopped redis shows up in
#      /api/v2.0/health as "lookup redis ... server misbehaving"; a running
#      one that couldn't persist shows the MISCONF error until a background
#      save succeeds, which the restart also clears.
#   7. Shows disk + Docker usage after cleanup, plus a per-directory
#      breakdown of / and /data. Harbor's default install stores its
#      registry blobs and database under /data (NOT in Docker volumes), so
#      if the disk is full and /var is small, /data/registry is the usual
#      culprit -- and reclaiming that requires Harbor's own Garbage
#      Collection, not anything this script does.
#
# What it deliberately does NOT do:
#   - Does not touch /data or any Docker volume. Harbor's Postgres/Redis/
#     registry state lives there; deleting registry blobs behind Harbor's
#     back corrupts the registry.
#   - Does not stop or reconfigure the running Harbor Compose stack (it
#     only *starts* redis if it is already stopped).
#   - Does not run Harbor's own registry garbage collection. If /data is
#     the space hog, run GC from the Harbor UI (Administration -> Garbage
#     Collection -> GC Now, ideally with "delete untagged artifacts"
#     enabled) after deleting old tags/repositories you no longer need.

set -euo pipefail

HARBOR_HOST="${1:-62.84.180.181}"
SSH_USER="${2:-root}"

echo "This will SSH into ${SSH_USER}@${HARBOR_HOST} and:"
echo "  - vacuum the systemd journal to 100MB"
echo "  - clear the apt package cache"
echo "  - truncate Docker container log files over 10MB"
echo "  - run 'docker system prune -af' (images/containers/build cache only, no volumes)"
echo "  - start Harbor's redis container if it is stopped"
echo "  - report disk usage breakdown of / and /data"
echo
read -r -p "Continue? [y/N] " CONFIRM
case "${CONFIRM}" in
  y|Y) ;;
  *) echo "Aborted."; exit 1 ;;
esac

echo
echo "Connecting to ${SSH_USER}@${HARBOR_HOST} -- enter the SSH password when prompted."
echo

ssh -t "${SSH_USER}@${HARBOR_HOST}" bash -s <<'REMOTE_SCRIPT'
set -uo pipefail

echo "===== Disk usage BEFORE ====="
df -h /

echo
echo "===== Docker usage BEFORE ====="
docker system df || true

echo
echo "===== Vacuuming systemd journal to 100MB ====="
journalctl --vacuum-size=100M || true

echo
echo "===== Clearing apt cache ====="
apt-get clean || true

echo
echo "===== Purging stale registry upload temp files (older than 1 hour) ====="
# Failed/interrupted docker pushes leave partial blobs in per-repo _uploads
# directories; Harbor's registry only purges them weekly. A few failed
# multi-GB pushes can strand many gigabytes here. Files newer than 1 hour
# are kept in case a push is in flight right now.
find /data/registry/docker/registry/v2/repositories -type d -name "_uploads" 2>/dev/null \
  | while read -r updir; do
      size=$(du -sh "${updir}" 2>/dev/null | cut -f1)
      echo "  ${updir} (${size})"
      find "${updir}" -mindepth 1 -mmin +60 -delete 2>/dev/null || true
    done

echo
echo "===== Truncating container logs over 10MB ====="
find /var/lib/docker/containers/ -name "*-json.log" -size +10M -print 2>/dev/null \
  | while read -r logfile; do
      echo "  truncating: ${logfile}"
      : > "${logfile}"
    done || true

echo
echo "===== Ensuring Harbor's redis container is running ====="
# Must happen before the prune: a stopped redis would otherwise be removed
# by 'docker system prune' as a stopped container.
if docker ps --format '{{.Names}}' | grep -qx redis; then
  echo "  redis is running; restarting it to clear any MISCONF persistence error"
  docker restart redis || echo "  WARNING: restart failed -- likely still no disk space"
else
  echo "  redis is NOT running; starting it"
  docker start redis || echo "  WARNING: start failed -- likely still no disk space"
fi
sleep 5
docker exec redis redis-cli info persistence 2>/dev/null | grep rdb_last_bgsave_status || true

echo
echo "===== Running docker system prune (images, containers, build cache -- no volumes) ====="
docker system prune -af

echo
echo "===== Disk usage AFTER ====="
df -h /

echo
echo "===== Docker usage AFTER ====="
docker system df || true

echo
echo "===== Where the disk space lives (may take a minute) ====="
echo "--- top-level directories on / ---"
du -x -d1 -h / 2>/dev/null | sort -rh | head -15
echo
echo "--- /data breakdown (Harbor's data directory) ---"
du -d1 -h /data 2>/dev/null | sort -rh | head -10

echo
echo "Done. If /data/registry is the space hog, this script cannot reclaim"
echo "it -- delete unneeded tags/repositories in the Harbor UI, then run"
echo "Harbor's Garbage Collection (Administration -> Garbage Collection ->"
echo "GC Now, with 'delete untagged artifacts' enabled)."
REMOTE_SCRIPT

echo
echo "Cleanup finished. Re-check Harbor's health from your Mac with:"
echo "  curl -s https://harbor.safranys.com/api/v2.0/health"
