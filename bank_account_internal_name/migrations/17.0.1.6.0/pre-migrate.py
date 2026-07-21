import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Force-drop the stale 2-column IBAN unique constraint.

    The base ``res.partner.bank`` defines
    ``unique_number = unique(sanitized_acc_number, partner_id)``. This module
    replaces it (same name) with a currency-aware
    ``unique(sanitized_acc_number, partner_id, currency_id)`` so one IBAN can
    exist once per currency (Revolut/Wise pockets).

    Odoo's automatic ``_sql_constraints`` sync is unreliable when a *non-owning*
    module overrides a base constraint: the old Postgres constraint frequently
    survives, so creating a second same-IBAN account still fails with the base
    message "The combination Account Number/Partner must be unique."

    We drop the constraint here in PRE-migrate (before the model's ``_auto_init``
    runs in the same ``-u``), so Odoo then recreates the correct 3-column
    constraint from the model definition. Idempotent — safe to re-run.
    """
    cr.execute(
        "ALTER TABLE res_partner_bank "
        "DROP CONSTRAINT IF EXISTS res_partner_bank_unique_number"
    )
    # Clear the bookkeeping row so _auto_init re-registers the constraint fresh
    # (and re-attributes ownership) instead of thinking it is unchanged.
    cr.execute(
        "DELETE FROM ir_model_constraint WHERE name = 'res_partner_bank_unique_number'"
    )
    _logger.info(
        "bank_account_internal_name: dropped stale unique_number constraint; "
        "_auto_init will recreate the currency-aware version."
    )
