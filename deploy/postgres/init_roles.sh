#!/bin/sh
set -eu

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${WORKBENCH_DB_RUNTIME_PASSWORD:?WORKBENCH_DB_RUNTIME_PASSWORD is required}"

psql --set ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set runtime_password="$WORKBENCH_DB_RUNTIME_PASSWORD" <<'SQL'
select 'create role workbench_runtime login'
where not exists (select 1 from pg_roles where rolname = 'workbench_runtime')\gexec

alter role workbench_runtime password :'runtime_password';
alter role workbench_runtime set statement_timeout = '15s';
alter role workbench_runtime set idle_in_transaction_session_timeout = '30s';
alter role workbench_runtime set lock_timeout = '5s';
SQL
