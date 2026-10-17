#!/usr/bin/env bash
# sudo bash deploy/backup/install.sh   — installs the hourly backup timer
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
command -v rclone >/dev/null || { echo "install rclone first: curl https://rclone.org/install.sh | sudo bash"; exit 1; }
[ -f /etc/gram-backup.env ] || { install -m 600 "$here/backup.env.example" /etc/gram-backup.env; echo "fill /etc/gram-backup.env and run again"; exit 1; }
chmod +x "$here/hourly_backup.sh"
sed "s#/opt/gram-city#$(cd "$here/../.." && pwd)#" "$here/gram-backup.service" > /etc/systemd/system/gram-backup.service
install -m 644 "$here/gram-backup.timer" /etc/systemd/system/gram-backup.timer
systemctl daemon-reload
systemctl enable --now gram-backup.timer
systemctl start gram-backup.service && echo "first backup done:" && ls -l /var/backups/gram/hourly | tail -n 2
