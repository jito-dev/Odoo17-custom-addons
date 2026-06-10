# -*- coding: utf-8 -*-

"""Pre-migration for 17.0.3.0.1.

Background: 17.0.3.0.0 (and earlier) registered the Settings menu
action as ``ir.actions.act_window`` under external_id
``simple_crypto_accounting.action_sca_settings``. That action opened
the singleton form with no ``res_id``, so saving would trip the
``UNIQUE(lock_field)`` constraint on ``sca.settings``.

17.0.3.0.1 reshapes the action into an ``ir.actions.server`` (calling
the model's ``_get_singleton().action_open_settings()`` helper). Odoo
refuses to redefine the same xmlid under a different model, so before
the new XML loads we delete the old ``ir.model.data`` row and the
underlying ``ir.actions.act_window`` record. The migration is idempotent
— missing rows are silently skipped — so a re-run is safe.
"""


def migrate(cr, version):
    cr.execute("""
        DELETE FROM ir_model_data
         WHERE module = 'simple_crypto_accounting'
           AND name   = 'action_sca_settings'
           AND model  = 'ir.actions.act_window'
        RETURNING res_id
    """)
    res_ids = [row[0] for row in cr.fetchall()]
    if res_ids:
        cr.execute(
            "DELETE FROM ir_act_window WHERE id IN %s",
            (tuple(res_ids),),
        )
