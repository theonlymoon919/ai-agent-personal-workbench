#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this installer as root." >&2
  exit 1
fi

project_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
apt-get update
apt-get install -y restic
chmod 0750 "$project_root/deploy/backup-cloud.sh"
ln -sfn "$project_root/deploy/backup-cloud.sh" /usr/local/sbin/personal-workbench-backup
install -m 0644 "$project_root/deploy/systemd/personal-workbench-backup.service" /etc/systemd/system/
install -m 0644 "$project_root/deploy/systemd/personal-workbench-backup.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now personal-workbench-backup.timer
systemctl start personal-workbench-backup.service
systemctl show personal-workbench-backup.service \
  --property=LoadState,ActiveState,SubState,Result,ExecMainStatus \
  --no-pager
systemctl list-timers --no-pager personal-workbench-backup.timer
