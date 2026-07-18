from odoo import api, models
from odoo.tools.misc import file_path

import logging

_logger = logging.getLogger(__name__)


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    @api.model
    def _repair_blank_arch_views(self):
        """Repair views whose ``arch`` cannot render as a parseable string.

        Symptom: rendering crashes in ``ir.ui.view._combine`` with
        ``etree.fromstring(None)`` -> ``ValueError: can only parse strings``,
        surfaced to the client as an ``RPC_ERROR`` that blocks every screen of
        the affected model.

        Two distinct causes — both handled here:

        1. **Missing source file under ``--dev xml`` (the common one after a prod
           restore).** With dev-xml on, ``_compute_arch`` reads a view's arch from
           its ``arch_fs`` file when ``arch_updated`` is False. If that file can't
           be resolved in this workspace, Odoo does ``arch_fs = False; continue``,
           leaving ``view.arch`` unset -> ``None``. The ``arch_db`` blob is still
           valid, so we FIX the row by clearing ``arch_fs`` and setting
           ``arch_updated = True`` (Odoo then always reads the DB arch). This pass
           is **dev-mode independent** — it tests file resolvability directly — so
           it also works from the ``-u`` post-migrate hook where dev-xml is off.

        2. **Genuinely empty ``arch_db``** (e.g. a broken web_studio row). Nothing
           to fall back to, so we DEACTIVATE it (reversible; never deleted). Caught
           by a runtime pass that reads the *computed* ``view.arch`` — exactly what
           ``_combine`` consumes.

        All mutations go through raw SQL to avoid the ORM ``write``/validation path
        re-parsing the very arch that is broken. Returns the number repaired.
        """
        prefer_db_ids = set()   # valid arch_db but broken file read -> use DB arch
        deactivate_ids = set()  # no usable arch anywhere -> deactivate

        def db_arch_of(view_id):
            self.env.cr.execute(
                "SELECT COALESCE(NULLIF(btrim(arch_db->>'en_US'), ''), '') "
                "FROM ir_ui_view WHERE id = %s",
                (view_id,),
            )
            return (self.env.cr.fetchone() or [''])[0]

        # ── Pass 1 (dev-mode independent): views that read arch from a file which
        # cannot be resolved here. These break the moment dev-xml is on.
        self.env.cr.execute("""
            SELECT v.id, v.arch_fs, v.key,
                   (d.id IS NOT NULL) AS has_xmlid
              FROM ir_ui_view v
              LEFT JOIN ir_model_data d
                     ON d.model = 'ir.ui.view' AND d.res_id = v.id
             WHERE v.active = true
               AND v.arch_fs IS NOT NULL
               AND COALESCE(v.arch_updated, false) = false
        """)
        for view_id, arch_fs, key, has_xmlid in self.env.cr.fetchall():
            # Odoo only reads from file when the view has an xml_id or a key.
            if not (has_xmlid or key):
                continue
            try:
                file_path(arch_fs)
            except (FileNotFoundError, ValueError):
                if db_arch_of(view_id):
                    prefer_db_ids.add(view_id)
                else:
                    deactivate_ids.add(view_id)

        # ── Pass 2 (runtime): read the computed arch exactly as _combine does, to
        # catch anything the targeted pass missed (blank arch_db, other causes).
        self.env.cr.execute("SELECT id FROM ir_ui_view WHERE active = true")
        for (view_id,) in self.env.cr.fetchall():
            if view_id in prefer_db_ids or view_id in deactivate_ids:
                continue
            # Prefetch just this id so a compute failure can't poison the others.
            view = self.browse(view_id).with_prefetch([view_id])
            try:
                arch = view.arch
            except Exception as exc:  # noqa: BLE001 - never abort the sweep
                arch = None
                _logger.warning('View repair: computing arch for id=%s raised %s',
                                 view_id, str(exc)[:200])
            if isinstance(arch, str) and arch.strip():
                continue  # healthy
            if db_arch_of(view_id):
                prefer_db_ids.add(view_id)
            else:
                deactivate_ids.add(view_id)

        if prefer_db_ids:
            self.env.cr.execute(
                "UPDATE ir_ui_view SET arch_updated = true, arch_fs = NULL "
                "WHERE id IN %s",
                (tuple(prefer_db_ids),),
            )
            _logger.warning(
                'View repair: forced DB arch (arch_updated=true, arch_fs cleared) '
                'on %s view(s) whose source file was unreadable: %s',
                len(prefer_db_ids), sorted(prefer_db_ids),
            )

        if deactivate_ids:
            self.env.cr.execute(
                "UPDATE ir_ui_view SET active = false WHERE id IN %s",
                (tuple(deactivate_ids),),
            )
            _logger.warning(
                'View repair: deactivated %s view(s) with an empty architecture '
                'and no file/DB fallback: %s',
                len(deactivate_ids), sorted(deactivate_ids),
            )

        total = len(prefer_db_ids) + len(deactivate_ids)
        if total:
            # Drop cached get_view()/combined-arch results so the repair is visible
            # immediately, and re-read the columns we changed by SQL.
            self.env.registry.clear_cache()
            self.invalidate_model(['arch_updated', 'arch_fs', 'active'])
        else:
            _logger.info('View repair: no broken views found.')
        return total
