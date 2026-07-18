import shlex
from pathlib import Path

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.modules.module import get_module_path

PRELUDE = (
    '# Run from a terminal — not from inside Odoo.\n'
    '# This will: ssh to the remote host, dump its DB + zip its filestore,\n'
    "# scp them back, drop+recreate the local 'restored_<db_name>' database,\n"
    '# restore both, run odoo-bin neutralize, and reinstall a few pip deps.\n'
    '# Expects DB_HOST / DB_USER / DB_PASSWORD / DOCKER_POSTGRES_CONTAINER_EXPOSE_PORT /\n'
    '# VENV_DIR to be present in your shell (the coder dev env sets them).\n'
)

NOTES = (
    "Steps the script performs on the remote host: psql \\conninfo, "
    "pg_dump (--format=custom --no-owner --no-acl), verify dump via "
    "pg_restore --list, zip the filestore folder so the archive holds "
    "only '<db_name>/<files>' (no absolute /var/lib/... prefix).\n"
    "Then locally: scp both artifacts back to /tmp, ssh rm -f the remote "
    "copies, unzip the filestore, dropdb --if-exists + createdb "
    "'restored_<db_name>', pg_restore -j 4, copy the filestore to "
    "/home/coder/.local/share/Odoo/filestore/restored_<db_name>/, "
    "odoo-bin neutralize, and finally reinstall paramiko<4.0.0 + "
    "markdownify + markdown + pydantic + openai + pysftp into the Odoo venv.\n"
    "On completion the script prints the start command — copy that line "
    "to launch Odoo against the restored database."
)


class JitoDbRefreshCommandWizard(models.TransientModel):
    _name = 'jito.db.refresh.command.wizard'
    _description = 'Jito DB Refresh — Render Command'

    remote_db_name = fields.Char(
        string='Remote DB Name',
        required=True,
        default='o.jito.dev',
        help="The Postgres database name on the remote host (e.g. "
             "'o.jito.dev'). The local restore will live in "
             "'restored_<remote_db_name>'.",
    )
    remote_host = fields.Char(
        string='Remote Host',
        required=True,
        default='209.38.240.237',
        help="IP or DNS name reachable via SSH. The script also uses this "
             "as the SCP source for the dump + filestore zip.",
    )
    remote_ssh_user = fields.Char(
        string='Remote SSH User',
        required=True,
        default='odoo',
        help="The OS user the script will SSH in as (must have read "
             "access to the filestore directory).",
    )
    remote_db_user = fields.Char(
        string='Remote DB User',
        required=True,
        default='odoo',
        help="The Postgres role used by pg_dump on the remote host. Also "
             "used to derive the default filestore folder path.",
    )
    remote_filestore_folder_path = fields.Char(
        string='Remote Filestore Folder',
        required=True,
        default='/var/lib/odoo/.local/share/Odoo/filestore',
        help="Parent directory of '<remote_db_name>/' on the remote host "
             "— what gets zipped. The script does a (cd <parent> && zip "
             "-r ... <remote_db_name>/) so the archive only contains the "
             "DB-name subfolder.",
    )

    restored_db_name = fields.Char(
        string='Local Restored DB',
        compute='_compute_render',
        readonly=True,
    )
    script_path_resolved = fields.Char(
        string='Script Path',
        compute='_compute_render',
        readonly=True,
    )
    command = fields.Text(
        string='Command',
        compute='_compute_render',
        readonly=True,
    )
    notes = fields.Text(
        string='Notes',
        compute='_compute_render',
        readonly=True,
    )

    @staticmethod
    def _resolve_script_path() -> str:
        module_path = get_module_path('jito_db_refresh')
        if not module_path:
            raise UserError(_('Cannot resolve jito_db_refresh module path.'))
        return str(Path(module_path) / 'scripts' / 'refresh-from-remote.sh')

    def action_repair_broken_views(self):
        """Deactivate any view with a NULL/empty architecture.

        Restores from production occasionally carry over web_studio views with a
        blank ``arch_db``; those crash rendering ("can only parse strings") and
        block a whole model in the UI. This is the on-demand counterpart of the
        automatic post-migrate repair — safe to click at any time (it only
        touches already-broken rows, and deactivation is reversible)."""
        self.ensure_one()
        fixed = self.env['ir.ui.view']._repair_blank_arch_views()
        message = (
            _('Repaired %s broken view(s). Reload any open screen that was '
              'failing.', fixed)
            if fixed else
            _('No broken (blank-architecture) views found — nothing to repair.')
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('View Repair'),
                'message': message,
                'type': 'success' if fixed else 'info',
                'sticky': False,
            },
        }

    @api.depends(
        'remote_db_name', 'remote_host', 'remote_ssh_user',
        'remote_db_user', 'remote_filestore_folder_path',
    )
    def _compute_render(self):
        script_path = self._resolve_script_path()
        for rec in self:
            rec.script_path_resolved = script_path
            rec.restored_db_name = (
                'restored_%s' % rec.remote_db_name if rec.remote_db_name else ''
            )
            envs = [
                ('REMOTE_HOST', rec.remote_host),
                ('REMOTE_SSH_USER', rec.remote_ssh_user),
                ('REMOTE_DB_USER', rec.remote_db_user),
                ('REMOTE_FILESTORE_FOLDER_PATH', rec.remote_filestore_folder_path),
            ]
            env_lines = ' \\\n'.join(
                '    %s=%s' % (k, shlex.quote(v or ''))
                for k, v in envs
            )
            rec.command = (
                PRELUDE
                + env_lines
                + ' \\\n    bash %s %s\n' % (
                    shlex.quote(script_path),
                    shlex.quote(rec.remote_db_name or ''),
                )
            )
            rec.notes = NOTES
