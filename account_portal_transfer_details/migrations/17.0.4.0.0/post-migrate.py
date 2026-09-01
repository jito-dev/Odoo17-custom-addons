import logging

_logger = logging.getLogger(__name__)

# The template every database created before this version carries, because it was the field's
# default. Matched in full and nothing else: a template somebody phrased themselves is their
# configuration, and overwriting it to "improve" it is how a fix becomes a regression.
_OLD_DEFAULT = "Software development services – Invoice {reference}"
_NEW_DEFAULT = "{services} – Invoice {reference}"


def migrate(cr, version):
    """ Move the untouched default onto the `{services}` placeholder.

    `default=` only ever runs for new records, so upgrading the module would otherwise change
    nothing on the portal: the providers already in the database would keep telling every
    customer, on every invoice, that they are paying for software development services.
    """
    cr.execute(
        """
        UPDATE payment_provider
           SET transfer_purpose_template = %s
         WHERE transfer_purpose_template = %s
        """,
        (_NEW_DEFAULT, _OLD_DEFAULT),
    )
    if cr.rowcount:
        _logger.info(
            "Payment purpose: moved %s wire transfer provider(s) from the fixed default to "
            "'%s'. The services now come from each invoice.", cr.rowcount, _NEW_DEFAULT
        )
