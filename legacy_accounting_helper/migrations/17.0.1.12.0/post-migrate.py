"""
Clean up stale ir.ui.view records that were left behind when:
  - jito_revolut_transactions module was deleted without being uninstalled
  - revolut_transaction_views.xml was removed from legacy_accounting_helper manifest
Any ir.ui.view row for revolut.transaction* models with a NULL arch will cause
'ValueError: can only parse strings' when Odoo tries to build the view hierarchy.
"""


def migrate(cr, version):
    # Remove all stale view records from the deleted jito_revolut_transactions module
    cr.execute("""
        DELETE FROM ir_ui_view
        WHERE module = 'jito_revolut_transactions'
    """)

    # Remove orphaned ir_model_data entries for the deleted module
    cr.execute("""
        DELETE FROM ir_model_data
        WHERE module = 'jito_revolut_transactions'
    """)

    # Remove any ir.ui.view rows for revolut.transaction* models that have a NULL
    # or empty arch — these are the direct cause of the ValueError
    cr.execute("""
        DELETE FROM ir_ui_view
        WHERE model IN ('revolut.transaction', 'revolut.transaction.leg')
          AND (arch IS NULL OR arch = '')
    """)

    # Invalidate the view cache so the clean records are loaded fresh
    cr.execute("""
        UPDATE ir_ui_view SET write_date = NOW()
        WHERE model IN ('revolut.transaction', 'revolut.transaction.leg')
    """)
