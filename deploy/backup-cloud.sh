#!/bin/sh
set -eu

project_root=${WORKBENCH_PROJECT_ROOT:-/opt/personal-workbench}
backup_root=${WORKBENCH_BACKUP_ROOT:-/var/backups/personal-workbench}
repository=$backup_root/repository
password_file=${WORKBENCH_BACKUP_PASSWORD_FILE:-/etc/personal-workbench/backup-password}
env_file=${WORKBENCH_ENV_FILE:-$project_root/.env.cloud}
compose_project=${COMPOSE_PROJECT_NAME:-personal-workbench}
backup_host=${WORKBENCH_BACKUP_HOST:-personal-workbench}
staging=

cleanup() {
  case "$staging" in
    "$backup_root"/staging.*)
      if [ -d "$staging" ]; then
        rm -rf -- "$staging"
      fi
      ;;
    '') ;;
    *)
      echo "Refusing to remove unexpected staging path" >&2
      ;;
  esac
}
trap cleanup EXIT INT TERM

cd "$project_root"
if [ ! -f "$env_file" ]; then
  echo "Environment file not found: $env_file" >&2
  exit 2
fi
set -a
. "$env_file"
set +a
umask 077
install -d -m 0700 "$backup_root"
install -d -m 0700 /etc/personal-workbench
if [ ! -f "$password_file" ]; then
  openssl rand -hex 32 > "$password_file"
  chmod 0600 "$password_file"
fi

export RESTIC_REPOSITORY=$repository
export RESTIC_PASSWORD_FILE=$password_file
if [ ! -f "$repository/config" ]; then
  restic init
fi

staging=$(mktemp -d "$backup_root/staging.XXXXXX")
docker compose --env-file "$env_file" -f compose.yaml -f compose.cloud.yaml exec -T postgres \
  pg_dump -U "${POSTGRES_USER:-workbench_owner}" -d "${POSTGRES_DB:-workbench}" --format=custom --no-owner --no-privileges \
  > "$staging/database.dump"

objects_path=$(docker volume inspect "${compose_project}_private-objects" --format '{{.Mountpoint}}')
test -d "$objects_path"

restic backup \
  "$staging/database.dump" \
  "$objects_path" \
  --host "$backup_host" \
  --tag scheduled

restic forget \
  --host "$backup_host" \
  --keep-daily 14 \
  --keep-weekly 8 \
  --keep-monthly 12 \
  --prune
restic check
