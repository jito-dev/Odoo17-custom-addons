# -*- coding: utf-8 -*-

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

MENUS_TO_UPDATE = [
    ('account.menu_finance', 'jito_icons,static/description/account/icon.png'),
    ('base.menu_administration', 'jito_icons,static/description/base/settings.png'),
    ('project.menu_main_pm', 'jito_icons,static/description/project/icon.png'),
]


def post_init_hook(cr, registry):
    """Update menu icons after module install/upgrade."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    _update_menu_icons(env)


def _update_menu_icons(env):
    """Update web_icon for Odoo root menus to use jito_icons assets."""
    for xmlid, web_icon in MENUS_TO_UPDATE:
        try:
            menu = env.ref(xmlid, raise_if_not_found=False)
            if menu and menu.web_icon != web_icon:
                menu.write({'web_icon': web_icon})
                _logger.info("jito_icons: updated %s", xmlid)
        except Exception as e:
            _logger.debug("jito_icons: could not update %s: %s", xmlid, e)
