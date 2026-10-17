#!/usr/bin/env bash
# GRAM City — hourly backup: code to GitHub + encrypted database copy to cloud storage.
# Installed by deploy/backup/install.sh, run every hour by gram-backup.timer.
# Settings: /etc/gram-backup.env (see backup.env.example). Never commit that file.
set -Eeuo pipefail

ENV_FILE="${GRAM_BACKUP_ENV:-/etc/gram-backup.env}"
[ -f "$ENV_FILE" ] && set -a && . "$ENV_FILE" && set +a

PROJECT_DIR="${PROJECT_DIR:?PROJECT_DIR is not set}"          # e.g. /opt/gram-city
LOCAL_DIR="${LOCAL_DIR:-/var/backups/gram}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"                              # e.g. b2:gram-backups  or  yandex:gram-backups
KEEP_HOURLY="${KEEP_HOURLY:-48}"
KEEP_DAILY="${KEEP_DAILY:-30}"
DAILY_HOUR="${DAILY_HOUR:-03}"                                   # the copy made in this hour (UTC) is also kept as a daily one
PYTHON="${PYTHON:-python3}"

STAMP="$(date -u +%Y-%m-%d_%H%M)"
HOUR="$(date -u +%H)"
LOG_TAG="gram-backup"

notify_fail() {
  local msg="⚠️ GRAM City: бэкап не выполнен ($STAMP UTC) — $1"
  logger -t "$LOG_TAG" "$msg" || true
  if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_ADMIN_ID:-}" ]; then
    curl -fsS -m 15 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${TELEGRAM_ADMIN_ID}" --data-urlencode "text=${msg}" >/dev/null || true
  fi
}
trap 'notify_fail "ошибка в строке $LINENO"' ERR

mkdir -p "$LOCAL_DIR/hourly" "$LOCAL_DIR/daily"
chmod 700 "$LOCAL_DIR"

# 1) code -> GitHub (only tracked + new files; .env files are in .gitignore)
if [ -d "$PROJECT_DIR/.git" ]; then
  cd "$PROJECT_DIR"
  git add -A
  if ! git diff --cached --quiet; then
    git -c user.name="${GIT_AUTHOR_NAME:-gram-backup}" -c user.email="${GIT_AUTHOR_EMAIL:-backup@localhost}" \
      commit -q -m "backup: $STAMP UTC"
  fi
  git push -q origin HEAD
fi

# 2) database -> encrypted file (AES-256-GCM, key BACKUP_KEY never leaves this machine's env file)
FILE="$LOCAL_DIR/hourly/gram_${STAMP}.enc"
if [ "${BACKUP_MODE:-host}" = "docker" ]; then
  # docker compose: the database is reachable only from the backend container
  cd "$PROJECT_DIR"
  TMP="/tmp/gram_${STAMP}.enc"
  docker compose exec -T -e BACKUP_KEY="$BACKUP_KEY" backend python -m scripts.backup_encrypted backup "$TMP" >/dev/null
  docker compose exec -T -e BACKUP_KEY="$BACKUP_KEY" backend python -m scripts.backup_encrypted verify "$TMP" >/dev/null
  docker compose cp "backend:$TMP" "$FILE"
  docker compose exec -T backend rm -f "$TMP"
  chmod 600 "$FILE"
else
  ( cd "$PROJECT_DIR/backend" && "$PYTHON" -m scripts.backup_encrypted backup "$FILE" ) >/dev/null
  ( cd "$PROJECT_DIR/backend" && "$PYTHON" -m scripts.backup_encrypted verify "$FILE" ) >/dev/null
fi
if [ "$HOUR" = "$DAILY_HOUR" ]; then cp -p "$FILE" "$LOCAL_DIR/daily/"; fi

# 3) local rotation: newest KEEP_HOURLY hourly, KEEP_DAILY daily
ls -1t "$LOCAL_DIR"/hourly/gram_*.enc 2>/dev/null | tail -n +$((KEEP_HOURLY + 1)) | xargs -r rm -f
ls -1t "$LOCAL_DIR"/daily/gram_*.enc  2>/dev/null | tail -n +$((KEEP_DAILY + 1))  | xargs -r rm -f

# 4) cloud copy (S3 / Backblaze B2 / Yandex Object Storage through rclone) — mirrors the rotated folders
if [ -n "$RCLONE_REMOTE" ]; then
  rclone sync -q "$LOCAL_DIR/hourly" "$RCLONE_REMOTE/hourly"
  rclone sync -q "$LOCAL_DIR/daily"  "$RCLONE_REMOTE/daily"
fi

logger -t "$LOG_TAG" "ok $FILE" || true
