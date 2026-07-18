# Jito DB Refresh

## Purpose
Bundle the validated `refresh-from-remote.sh` script inside an Odoo
module and provide a tiny wizard UI that **renders the exact
command** the operator needs to paste into a terminal to refresh the
local DB + filestore from a remote production host.

**The module never executes the script.** Same UX as `jito_prod_fork`:
fill in the inputs → copy the rendered command → run it in a shell.
A "Run Now" button is intentionally out of scope (see "Boundaries"
below).

## Main Components

### `scripts/refresh-from-remote.sh`
The script verbatim. Reads `REMOTE_HOST`, `REMOTE_SSH_USER`,
`REMOTE_DB_USER`, `REMOTE_FILESTORE_FOLDER_PATH` from env (with
sensible defaults baked in) and takes the remote DB name as `$1`.
SSHs into the remote host to dump + zip; scp's the artifacts back;
restores into a local `restored_<remote_db_name>` database; copies
the filestore under `/home/coder/.local/share/Odoo/filestore/...`;
runs `odoo-bin neutralize`; reinstalls a few pip deps; prints the
start command.

The script also expects `DB_HOST`, `DB_USER`, `DB_PASSWORD`,
`DOCKER_POSTGRES_CONTAINER_EXPOSE_PORT`, and `VENV_DIR` to be set in
the shell — the coder dev environment provides them. **Run the
generated command in the same shell you'd use to launch Odoo.**

### `jito.db.refresh.command.wizard` (TransientModel)
Holds the input fields and the computed `command` text:

- `remote_db_name`, `remote_host`, `remote_ssh_user`,
  `remote_db_user`, `remote_filestore_folder_path` — editable inputs
  with operationally sane defaults.
- `script_path_resolved` — read-only; computed via
  `odoo.modules.module.get_module_path('jito_db_refresh')` so the
  rendered command always points at the script that ships with the
  installed module.
- `restored_db_name` — read-only; computed as
  `'restored_' + remote_db_name`.
- `command` — read-only Text; the env-prefixed `bash <path>
  <db_name>` one-liner with each value `shlex.quote`'d so unusual
  characters can't break the command.
- `notes` — read-only Text; plain-English summary of every step the
  script will run.

### Form view
`view_jito_db_refresh_command_wizard_form` renders the inputs, the
resolved fields, the monospaced `command` block, and the notes. A
single "Close" footer button — no "Run".

### Action + menu
- `action_jito_db_refresh_command_wizard` — `ir.actions.act_window`
  with `target='new'` so the wizard opens as a modal.
- Top-level menu **"DB Refresh" → "Refresh from Remote"**, gated by
  `base.group_system`. We tried `base.menu_database` first; that
  xmlid isn't shipped in this Odoo install (loader raised
  "External ID not found: base.menu_database"). A dedicated root
  matches `jito_prod_fork`'s pattern and avoids depending on stock
  menu xmlids that drift between versions.

## Post-Restore View Repair (17.0.1.0.4)
After a production DB restore, opening some screens crashes with
`ValueError: can only parse strings` (an `RPC_ERROR` in the browser), blocking
**every screen of the affected model**. It happens in `ir.ui.view._combine` at
`etree.fromstring(view.arch)` when the computed `arch` is `None`.

**Root cause (this workspace runs `--dev=all`, which includes `xml`).** With
dev-xml on, `ir.ui.view._compute_arch` reads a view's arch from its `arch_fs`
**source file** whenever `arch_updated` is False. A restored view can reference a
file that doesn't resolve here; Odoo then does `arch_fs = False; continue`,
leaving `view.arch` unset (`None`). The `arch_db` blob is still valid — the crash
is purely the failed file read. (A rarer second cause is a genuinely empty
`arch_db`, e.g. a broken web_studio row.)

`models/ir_ui_view._repair_blank_arch_views()` — two passes, all mutations in raw
SQL (never the ORM `write`/validation path, which would re-parse the broken arch):
- **Pass 1 (dev-mode independent):** for active views with `arch_fs` set,
  `arch_updated` False, and an xml_id/key, test `file_path(arch_fs)`. If it can't
  be resolved and `arch_db` has content -> set `arch_updated = true` and clear
  `arch_fs` so Odoo always uses the DB arch. This is the real fix and works even
  from the `-u` hook where dev-xml is off.
- **Pass 2 (runtime):** read the *computed* `view.arch` (exactly what `_combine`
  consumes) for every active view; anything still non-string with valid `arch_db`
  -> Pass-1 fix, otherwise -> **deactivate** (reversible; never deleted).

Entry points:
- `migrations/17.0.1.0.4/post-migrate.py` — runs the repair on every
  `-u jito_db_refresh` (hence the deploy pipeline's `-u all`). No manual SQL.
- `jito.db.refresh.command.wizard.action_repair_broken_views` — a
  **"Repair Broken Views"** button on the wizard form. Run it in the **live**
  (dev-xml) server for on-demand repair; the wizard menu still loads because only
  the broken model's own screens fail. Safe/idempotent.

> Non-destructive: Pass 1 only flips `arch_updated`/`arch_fs` (the DB arch is
> unchanged); Pass 2 deactivation is reversible. Healthy views are never touched.

## Security
Only `base.group_system` (Settings Administrators) has access to
the wizard model and sees the menu. The rendered command, when
pasted, will drop and recreate a local DB and overwrite a local
filestore folder, so no lower-privileged groups are intentional.

## Boundaries (do not "improve")
- **Do not add a "Run Now" button.** The user explicitly designed
  this as a command-emitter, not a runner. Executing the script
  inside Odoo would require shelling out from the HTTP worker,
  handling multi-minute timeouts, capturing logs across an SSH
  call + scp, and surfacing pid/log state via cron or bus.bus —
  all explicitly out of scope.
- **Do not modify the bundled script's contents.** It's the
  user-validated version from `/home/coder/bin/refresh-from-remote.sh`
  at module-creation time; updates should come from there and be
  copied over verbatim.
- **Do not switch to `models.Model`.** A TransientModel keeps the
  wizard ephemeral and auto-vacuumed; there's no need for run
  history (the shell command itself records everything via
  `set -x`).
