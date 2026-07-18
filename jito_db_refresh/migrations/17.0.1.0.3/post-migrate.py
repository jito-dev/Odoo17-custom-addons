"""Auto-repair blank-arch views left behind by a production DB restore.

Runs on every ``-u jito_db_refresh`` (and therefore on the ``-u all`` the deploy
pipeline performs). A view whose ``arch_db`` is NULL/empty crashes rendering with
``ValueError: can only parse strings`` and blocks the whole model in the UI; this
deactivates such rows so the screens load again. Reversible (active=False, not
deleted). See ``models/ir_ui_view._repair_blank_arch_views``.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    fixed = env['ir.ui.view']._repair_blank_arch_views()
    _logger.info('jito_db_refresh post-migrate: repaired %s blank-arch view(s).', fixed)
