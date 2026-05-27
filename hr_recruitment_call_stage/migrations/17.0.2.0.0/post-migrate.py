# -*- coding: utf-8 -*-
"""Post-migrate for 17.0.1.2.0 → 17.0.2.0.0 (Etap 2: native swap).

Unregister the removed `hr.applicant.booking.invite` model from
ir.model. Unlinking the ir.model record cascades to ir.model.fields,
ir.model.access, ir.model.data — Odoo's standard cleanup path.

The actual table was already renamed to ``..._etap2_backup`` in
pre-migrate; we do not drop it here so a rollback remains possible.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # `_force_unlink` lets ir.model.unlink() drop Python-defined fields
    # (state='base'); without it Odoo refuses with "This column contains
    # module data and cannot be removed!" because it assumes the unlink
    # came from user-driven studio edits.
    env = api.Environment(cr, SUPERUSER_ID, {'_force_unlink': True})
    model = env['ir.model'].with_context(_force_unlink=True).search(
        [('model', '=', 'hr.applicant.booking.invite')], limit=1)
    if not model:
        _logger.info(
            "hr_recruitment_call_stage 17.0.2.0.0: ir.model entry already "
            "absent — nothing to unlink.")
        return

    # Strip ir.model.data rows that still anchor the model, its fields,
    # and its ACLs to *any* module. _prepare_update() refuses to drop
    # columns claimed by a module other than the one being upgraded —
    # since the model is gone for good in this version, all such
    # anchors are stale and must go before unlink().
    field_ids = env['ir.model.fields'].search(
        [('model_id', '=', model.id)]).ids
    access_ids = env['ir.model.access'].search(
        [('model_id', '=', model.id)]).ids
    cr.execute(
        "DELETE FROM ir_model_data "
        " WHERE (model = 'ir.model'        AND res_id  = %s) "
        "    OR (model = 'ir.model.fields' AND res_id = ANY(%s)) "
        "    OR (model = 'ir.model.access' AND res_id = ANY(%s))",
        (model.id, field_ids or [0], access_ids or [0]),
    )
    env.invalidate_all()
    model.unlink()
    _logger.info(
        "hr_recruitment_call_stage 17.0.2.0.0: removed ir.model entry for "
        "hr.applicant.booking.invite (cascades fields/access/data).",
    )
