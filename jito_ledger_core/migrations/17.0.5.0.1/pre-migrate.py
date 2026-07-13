# -*- coding: utf-8 -*-

"""Pre-migrate to 17.0.5.0.1 — purge the removed ``jito_ledger_extension``
module and the retired ``kind='extension'`` ledger.

17.0.5.0.1 deletes the ``jito_ledger_extension`` module (Extension Ledger
UX polish) and drops the ``kind='extension'`` ledger. On databases where
that module was installed (e.g. restored snapshots), its inherited view on
the ``jito.ledger`` form lingers in ``ir_ui_view`` after the code is gone.
Its source file no longer exists and its ``arch_db`` is empty, so when the
``jito.ledger`` form is combined that child view yields ``view.arch = None``
and ``etree.fromstring`` raises ``ValueError: can only parse strings`` —
crashing "Ledgers → Non-Leading Ledger".

This runs as a **pre**-migrate (before ``jito_ledger_core`` rewrites its
own ``jito.ledger`` form view) using raw SQL, so the parent form's
``_check_xml`` combine-validation never touches the broken child. Every
statement is defensive: the crash-fixing deletes touch only ``ir_ui_view``
/ ``ir_model_data`` (always present) and run first, and anything that
references optional tables is guarded with ``to_regclass`` so a missing
table can never roll the whole migration back. It no-ops on databases
where the module was never installed.

Migration scripts in Odoo 17 use ``migrate(cr, version)``.
"""

import logging

_logger = logging.getLogger(__name__)

_DEAD_MODULE = 'jito_ledger_extension'


def _table_exists(cr, table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return cr.fetchone()[0] is not None


def migrate(cr, version):
    # === Crash fix (runs first, no optional-table dependencies) ==========

    # 1a. Delete any *inherited* jito.ledger view whose arch_db is NULL. A
    #     view with no stored arch can never render — it is by definition a
    #     broken orphan. Scoped to model 'jito.ledger' so nothing else is
    #     touched. NB: arch_db is a translated (jsonb) column, so only the
    #     NULL test is valid here — a string comparison like ``= ''`` raises
    #     ``invalid input syntax for type json``.
    cr.execute("""
        DELETE FROM ir_ui_view
         WHERE model = 'jito.ledger'
           AND inherit_id IS NOT NULL
           AND arch_db IS NULL
    """)
    broken = cr.rowcount

    # 1b. Delete views the dead module owns — by xmlid and by on-disk arch
    #     source path — covering any that still carry an arch_db.
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = %s AND model = 'ir.ui.view'
    """, (_DEAD_MODULE,))
    view_ids = {row[0] for row in cr.fetchall()}
    cr.execute(
        "SELECT id FROM ir_ui_view WHERE arch_fs LIKE %s",
        (_DEAD_MODULE + '/%',),
    )
    view_ids |= {row[0] for row in cr.fetchall()}
    if view_ids:
        cr.execute("DELETE FROM ir_ui_view WHERE id IN %s", (tuple(view_ids),))
    if broken or view_ids:
        _logger.info(
            "jito_ledger_core 17.0.5.0.1: removed %d broken/orphaned "
            "jito.ledger view(s) from the deleted %s module.",
            broken + len(view_ids), _DEAD_MODULE,
        )

    # 2. Drop every leftover xmlid the module owns (views already gone;
    #    this also unhooks its actions / menus).
    cr.execute("DELETE FROM ir_model_data WHERE module = %s", (_DEAD_MODULE,))

    # === Best-effort cleanup (guarded; never aborts the crash fix) =======

    # 3. Remove extension-kind ledgers that nothing references. Guarded on
    #    table presence so a not-yet-created table can't error the run.
    if _table_exists(cr, 'jito_ledger'):
        conditions = ["l.kind = 'extension'"]
        if _table_exists(cr, 'jito_ledger_journal'):
            conditions.append(
                "NOT EXISTS (SELECT 1 FROM jito_ledger_journal j "
                "WHERE j.ledger_id = l.id)"
            )
        if _table_exists(cr, 'jito_ledger_move'):
            conditions.append(
                "NOT EXISTS (SELECT 1 FROM jito_ledger_move m "
                "WHERE m.ledger_id = l.id)"
            )
        cr.execute(
            "DELETE FROM jito_ledger l WHERE " + " AND ".join(conditions)
        )
        if cr.rowcount:
            _logger.info(
                "jito_ledger_core 17.0.5.0.1: deleted %d unreferenced "
                "extension ledger record(s).", cr.rowcount,
            )

    # 4. Mark the module uninstalled so Apps no longer reports it installed.
    cr.execute("""
        UPDATE ir_module_module
           SET state = 'uninstalled'
         WHERE name = %s
           AND state NOT IN ('uninstalled', 'uninstallable')
    """, (_DEAD_MODULE,))
    if cr.rowcount:
        _logger.info(
            "jito_ledger_core 17.0.5.0.1: marked %s uninstalled.",
            _DEAD_MODULE,
        )
