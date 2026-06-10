# -*- coding: utf-8 -*-

"""Post-migrate to 17.0.1.3.0 — remove the legacy "Sync FAAP Mirrors"
menu item.

Up to 17.0.1.2.x the FAAP sync wizard was launched from a menu item
under Configuration. From 17.0.1.3.0 it's launched from a header
button on the FAAP Mirrors tree view, so the menu is redundant. We
remove the orphan record explicitly because Odoo doesn't auto-clean
records merely removed from XML data files.

Idempotent: a re-run finds nothing to remove. Safe on installs that
never had 17.0.1.2.x (the lookup just returns no record).
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    menu = env.ref(
        'jito_ledger_core.menu_jito_ledger_faap_sync',
        raise_if_not_found=False,
    )
    if menu:
        menu.unlink()
        _logger.info(
            "jito_ledger_core 17.0.1.3.0: removed legacy "
            "menu_jito_ledger_faap_sync; FAAP sync is now a "
            "header button on the FAAP Mirrors tree view."
        )
