"""Backfill account_map_id, transfer_other_account_map_id, and source on revolut_transaction."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    _logger.info("Backfilling account_map_id on revolut_transaction...")
    cr.execute("""
        UPDATE revolut_transaction rt
        SET account_map_id = rajm.id
        FROM revolut_account_journal_map rajm
        WHERE rt.account_revolut_id = rajm.revolut_account_id
          AND rt.company_id = rajm.company_id
          AND rt.account_map_id IS NULL
    """)
    _logger.info("  → %d rows updated (account_map_id)", cr.rowcount)

    _logger.info("Backfilling transfer_other_account_map_id...")
    cr.execute("""
        UPDATE revolut_transaction rt
        SET transfer_other_account_map_id = rajm.id
        FROM revolut_account_journal_map rajm
        WHERE rt.transfer_other_account_id = rajm.revolut_account_id
          AND rt.company_id = rajm.company_id
          AND rt.transfer_other_account_map_id IS NULL
          AND rt.transfer_between_accounts = TRUE
    """)
    _logger.info("  → %d rows updated (transfer_other_account_map_id)", cr.rowcount)

    _logger.info("Backfilling source field...")
    cr.execute("""
        UPDATE revolut_transaction
        SET source = 'csv'
        WHERE transaction_type IN ('fcf_buy', 'fcf_sell', 'fcf_interest', 'fcf_fee')
          AND (source IS NULL OR source != 'csv')
    """)
    _logger.info("  → %d rows set to 'csv'", cr.rowcount)

    cr.execute("""
        UPDATE revolut_transaction
        SET source = 'api'
        WHERE source IS NULL
    """)
    _logger.info("  → %d rows set to 'api'", cr.rowcount)
