"""
Pre-migration: purge ALL stale ir.ui.view records for revolut.transaction* models
before the module data files are reloaded.

Note: ir_ui_view has no 'module' column — module ownership lives in ir_model_data.
"""


def migrate(cr, version):
    # 1. Delete ALL views for revolut.transaction* models regardless of source.
    #    The XML data files recreate them cleanly right after this pre-migrate runs.
    cr.execute("""
        DELETE FROM ir_ui_view
        WHERE model IN ('revolut.transaction', 'revolut.transaction.leg')
    """)

    # 2. Remove the corresponding ir_model_data rows so Odoo doesn't try to
    #    match them against the now-deleted view records (avoids duplicate key errors).
    cr.execute("""
        DELETE FROM ir_model_data
        WHERE model = 'ir.ui.view'
          AND module IN (
              'legacy_accounting_helper',
              'jito_revolut_transactions',
              'revolut_accounting_helper'
          )
          AND name IN (
              'view_revolut_transaction_search',
              'view_revolut_transaction_tree',
              'view_revolut_transaction_form',
              'action_revolut_transactions',
              'action_revolut_helper_transactions'
          )
    """)

    # 3. Clean up all ir_model_data rows from the deleted jito_revolut_transactions module.
    cr.execute("""
        DELETE FROM ir_model_data
        WHERE module = 'jito_revolut_transactions'
    """)

    # 4. Delete any remaining ir_ui_view records linked to jito_revolut_transactions
    #    via ir_model_data (join required since ir_ui_view has no module column).
    cr.execute("""
        DELETE FROM ir_ui_view
        WHERE id IN (
            SELECT res_id FROM ir_model_data
            WHERE module = 'jito_revolut_transactions'
              AND model = 'ir.ui.view'
        )
    """)
