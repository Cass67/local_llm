#!/usr/bin/env bash
# Move the gitlab container to another GitLab CE version.
#
#   scripts/gitlab-upgrade.sh 18.5.7-ce.0     # set container/Dockerfile.gitlab, then upgrade
#   scripts/gitlab-upgrade.sh                 # (re)apply whatever the Dockerfile says
#   scripts/gitlab-upgrade.sh --no-backup 18.5.7-ce.0
#
# Run on the GitLab host from the repo checkout. One required stop per run:
# https://docs.gitlab.com/update/upgrade_paths/ (x.2, x.5, x.8, x.11, latest
# patch of each). Each run:
#   1. refuses to start while batched background migrations are unfinished,
#   2. takes a gitlab-backup + config tar (secrets included) unless --no-backup,
#   3. on a jump to 19+, upgrades bundled PostgreSQL to 17 first if still on 16
#      (19.0 needs it; 18.11's image normally does this itself on first start),
#   4. rebuilds the image, recreates the container, waits for healthy,
#   5. waits for the new version's background migrations to finish.
#
# Rollback: restore the backup taken in step 2 on the OLD version (put the old
# tag back in the Dockerfile, rerun with --no-backup, then gitlab-backup restore
# and untar the config). Backups only restore onto the exact version that made them.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DOCKERFILE="$REPO/container/Dockerfile.gitlab"
GITLAB_DIR="${GITLAB_DIR:-/mnt/models/gitlab}"
BACKUP_DIR="${GITLAB_BACKUP_DIR:-/mnt/backup/local_llm-backups/gitlab}"
BACKUP=1

if [[ "${1:-}" == "--no-backup" ]]; then
  BACKUP=0
  shift
fi
if [[ -n "${1:-}" ]]; then
  [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+-ce\.0$ ]] || {
    echo "bad version: $1 (want e.g. 18.5.7-ce.0)" >&2
    exit 2
  }
  sed -i "s/^ARG GITLAB_VERSION=.*/ARG GITLAB_VERSION=$1/" "$DOCKERFILE"
fi
TARGET="$(sed -n 's/^ARG GITLAB_VERSION=//p' "$DOCKERFILE")"

say() { echo "[$(date +%T)] $*"; }
rails() { docker exec gitlab gitlab-rails runner -e production "$1"; }
running() { docker exec gitlab sed -n '1s/^gitlab-ce //p' /opt/gitlab/version-manifest.txt; }

wait_migrations() {
  local n failed
  while true; do
    # rails runner takes ~1 min to boot, so both counts in one call. Failed
    # migrations whose job class GitLab has since deleted (2022-era leftovers
    # here) can never run again and no upgrade checks them, so they don't count.
    # Gitlab::BackgroundMigration.remaining (sidekiq-style migrations) is gone in 18.5+.
    read -r n failed < <(rails 'm = Gitlab::Database::BackgroundMigration::BatchedMigration
      b = Gitlab::BackgroundMigration
      f = m.with_status(:failed).count { |x| b.const_defined?(x.job_class_name, false) }
      puts "#{m.queued.count + (b.respond_to?(:remaining) ? b.remaining : 0)} #{f}"' | tail -1)
    if [[ "$failed" != 0 ]]; then
      say "$failed failed batched migration(s): Admin > Monitoring > Background migrations. Fix before upgrading."
      exit 1
    fi
    [[ "$n" == 0 ]] && return
    say "background migrations remaining: $n"
    sleep 30
  done
}

wait_healthy() {
  local s
  for _ in $(seq 120); do
    s="$(docker inspect gitlab --format '{{.State.Health.Status}}' 2>/dev/null || echo missing)"
    # healthy only covers nginx/puma; 18.11's first start reports healthy while
    # it stops postgres for its automatic PG 16 -> 17 upgrade
    if [[ "$s" == healthy ]]; then
      # gitlab-ctl status exits non-zero while anything is down; || true for pipefail
      (docker exec gitlab gitlab-ctl status || true) | grep -q '^down:' || return 0
      s="healthy, services still down"
    fi
    [[ "$(docker inspect gitlab --format '{{.State.Restarting}}')" == true ]] && say "container restarting"
    say "health: $s"
    sleep 15
  done
  say "not healthy after 30 min; docker logs gitlab"
  exit 1
}

FROM="$(running)"
say "running $FROM, target $TARGET"
wait_migrations

if ((BACKUP)); then
  TS="$(date +%Y%m%d-%H%M%S)"
  say "backup gitlab-$TS"
  mkdir -p "$BACKUP_DIR"
  docker exec gitlab gitlab-backup create STRATEGY=copy CRON=1 BACKUP="gitlab-$TS-$FROM"
  sudo mv "$GITLAB_DIR/data/backups/gitlab-$TS-${FROM}_gitlab_backup.tar" "$BACKUP_DIR/"
  sudo tar -C "$GITLAB_DIR" -cf "$BACKUP_DIR/gitlab-$TS-$FROM-config.tar" config
  sudo chmod 0600 "$BACKUP_DIR/gitlab-$TS-${FROM}_gitlab_backup.tar" "$BACKUP_DIR/gitlab-$TS-$FROM-config.tar"
fi

PG="$(docker exec gitlab /opt/gitlab/embedded/bin/psql --version | grep -oE '[0-9]+' | head -1)"
if ((${TARGET%%.*} >= 19 && PG < 17)); then
  say "PostgreSQL $PG -> 17 (required by 19.0)"
  docker exec gitlab gitlab-ctl pg-upgrade -V 17
fi

say "build + recreate"
docker compose -p local_llm --project-directory "$REPO" build gitlab
docker compose -p local_llm --project-directory "$REPO" up -d --no-deps gitlab
wait_healthy
wait_migrations
say "done: $FROM -> $(running)"
