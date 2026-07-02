#!/bin/bash
set -euo pipefail
set -x

# ---- Inputs ----------------------------------------------------------
REMOTE_HOST="${REMOTE_HOST:-209.38.240.237}"
REMOTE_SSH_USER="${REMOTE_SSH_USER:-odoo}"     # SSH user
REMOTE_DB_NAME="${1:-o.jito.dev}"
REMOTE_DB_USER="${REMOTE_DB_USER:-odoo}"       # Postgres role on remote
REMOTE_FILESTORE_FOLDER_PATH="${REMOTE_FILESTORE_FOLDER_PATH:-/var/lib/${REMOTE_DB_USER}/.local/share/Odoo/filestore}"

REMOTE="${REMOTE_SSH_USER}@${REMOTE_HOST}"

# ---- Derived paths (resolved LOCALLY so they're shared with remote) --
TIMESTAMP="$(date +%y%m%d-%H%M%S)"
OUT_DB_DUMP_FILENAME="${REMOTE_DB_NAME}-${TIMESTAMP}.dump"
OUT_DB_DUMP_FILEPATH="/tmp/${OUT_DB_DUMP_FILENAME}"
OUT_FILESTORE_ZIP_FILENAME="filestore-${REMOTE_DB_NAME}-${TIMESTAMP}.zip"
OUT_FILESTORE_ZIP_FILEPATH="/tmp/${OUT_FILESTORE_ZIP_FILENAME}"

# ====================== REMOTE: probe + dump =========================
# Unquoted heredoc → ${...} variables are expanded by THIS shell before
# being sent to the remote, so the remote bash literally sees the
# resolved paths/names. Backslashes that should reach the remote shell
# (e.g. psql's `\conninfo`) need to be escaped as `\\`.
ssh "${REMOTE}" bash -s <<EOF
set -euo pipefail
set -x

psql -d "${REMOTE_DB_NAME}" -c '\\conninfo'

pg_dump --format=custom --no-owner --no-acl \\
        --file="${OUT_DB_DUMP_FILEPATH}" "${REMOTE_DB_NAME}"
if pg_restore --list "${OUT_DB_DUMP_FILEPATH}" > /dev/null; then
    echo "Exported ${OUT_DB_DUMP_FILEPATH} is OK"
else
    echo "Exported ${OUT_DB_DUMP_FILEPATH} is CORRUPTED"
    exit 1
fi

# Subshell cd so the archive holds only "<db_name>/<files>" — no
# absolute /var/lib/... prefix.
( cd "${REMOTE_FILESTORE_FOLDER_PATH}" \\
  && zip -r "${OUT_FILESTORE_ZIP_FILEPATH}" "${REMOTE_DB_NAME}/" > /dev/null )
EOF

# ====================== LOCAL: download =============================
scp "${REMOTE}:${OUT_DB_DUMP_FILEPATH}"       "${OUT_DB_DUMP_FILEPATH}"
scp "${REMOTE}:${OUT_FILESTORE_ZIP_FILEPATH}" "${OUT_FILESTORE_ZIP_FILEPATH}"

# ====================== REMOTE: cleanup =============================
ssh "${REMOTE}" "rm -f '${OUT_DB_DUMP_FILEPATH}' '${OUT_FILESTORE_ZIP_FILEPATH}'"

# ====================== LOCAL: restore ==============================
cd /tmp/
unzip -o "${OUT_FILESTORE_ZIP_FILEPATH}"
UNZIPED_FILESTORE="/tmp/${REMOTE_DB_NAME}"

sudo apt install -y postgresql-client

# Coder env passes these in
export PGHOST="${DB_HOST}"
export PGUSER="${DB_USER}"
export PGPASSWORD="${DB_PASSWORD}"
export PGPORT="${DOCKER_POSTGRES_CONTAINER_EXPOSE_PORT}"
export RESTORED_DB_NAME="restored_${REMOTE_DB_NAME}"

dropdb --if-exists "${RESTORED_DB_NAME}"
createdb "${RESTORED_DB_NAME}"
pg_restore --no-owner --no-acl -j 4 -d "${RESTORED_DB_NAME}" "${OUT_DB_DUMP_FILEPATH}"

RESTORED_FILESTORE_LOCAL="/home/coder/.local/share/Odoo/filestore/${RESTORED_DB_NAME}"
mkdir -p "${RESTORED_FILESTORE_LOCAL}"
# `${dir}/.` copies dotfiles too; `${dir}/*` inside double-quotes would
# NOT glob — that's why the original was silently no-op.
cp -r "${UNZIPED_FILESTORE}/." "${RESTORED_FILESTORE_LOCAL}/"

ODOO_BIN="/home/coder/src/odoo/odoo17_community/odoo-bin"
"${ODOO_BIN}" neutralize -d "${RESTORED_DB_NAME}" \
    --db_host="${PGHOST}" --db_user="${PGUSER}" --db_password="${PGPASSWORD}"

rm -rf "${OUT_DB_DUMP_FILEPATH}" "${OUT_FILESTORE_ZIP_FILEPATH}" "/tmp/${REMOTE_DB_NAME}"

ODOO_VENV_PIP="/home/coder/.venv/odoo17/bin/pip"
"${ODOO_VENV_PIP}" install --force-reinstall 'paramiko<4.0.0'
"${ODOO_VENV_PIP}" install markdownify markdown pydantic openai

echo "Run DB_NAME=${RESTORED_DB_NAME} /home/coder/bin/odoo.sh start"
