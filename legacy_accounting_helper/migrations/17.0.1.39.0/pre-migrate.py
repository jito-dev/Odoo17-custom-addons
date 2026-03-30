import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Drop the old unique constraint so the ORM can create the wider one."""
    _logger.info(
        "Dropping old revolut_transaction_revolut_id_company_uniq constraint "
        "to allow per-account records for internal transfers."
    )
    cr.execute("""
        ALTER TABLE revolut_transaction
        DROP CONSTRAINT IF EXISTS revolut_transaction_revolut_id_company_uniq
    """)
