from odoo import api, models

import logging

_logger = logging.getLogger(__name__)


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    @api.model
    def _repair_blank_arch_views(self):
        """Deactivate views whose ``arch_db`` is NULL/empty.

        A view with a blank architecture makes ``view.arch`` resolve to
        ``None`` (``ir_ui_view._compute_arch`` -> ``to_text(arch_fs or arch_db)``).
        When such a view participates in a combine hierarchy, rendering crashes
        with ``etree.fromstring(None)`` -> ``ValueError: can only parse strings``,
        which surfaces to the client as an ``RPC_ERROR`` and blocks every screen
        of the affected model.

        These rows are almost always web_studio customisations that arrive with a
        NULL ``arch_db`` after a production DB restore (see ``jito_db_refresh``):
        a broken, non-functional view. We DEACTIVATE (never delete) so the change
        is fully reversible, and we do it in raw SQL to avoid the ORM ``write``
        path re-parsing the very arch that is broken.

        Returns the number of views deactivated.
        """
        # ``arch_db`` is a translated Text field -> stored as jsonb in Odoo 17.
        # A truly-empty value is NULL, ``{}``, or an empty ``en_US`` term.
        self.env.cr.execute("""
            SELECT id, model, mode, inherit_id
              FROM ir_ui_view
             WHERE active = true
               AND (
                    arch_db IS NULL
                 OR arch_db::text IN ('{}', 'null', '""')
                 OR COALESCE(NULLIF(btrim(arch_db->>'en_US'), ''), '') = ''
               )
        """)
        rows = self.env.cr.fetchall()
        if not rows:
            _logger.info('Blank-arch view repair: nothing to fix.')
            return 0

        ids = [r[0] for r in rows]
        for view_id, model, mode, inherit_id in rows:
            _logger.warning(
                'Blank-arch view repair: deactivating view id=%s (model=%s, '
                'mode=%s, inherit_id=%s) — it has an empty architecture and '
                'would crash rendering with "can only parse strings".',
                view_id, model, mode, inherit_id,
            )

        self.env.cr.execute(
            "UPDATE ir_ui_view SET active = false WHERE id IN %s",
            (tuple(ids),),
        )
        # Invalidate ORM + get_view caches so the now-inactive views drop out of
        # every combine hierarchy immediately.
        self.env.registry.clear_cache()
        self.invalidate_model(['active'])

        _logger.warning(
            'Blank-arch view repair: deactivated %s broken view(s): %s',
            len(ids), ids,
        )
        return len(ids)
