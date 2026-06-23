# -*- coding: utf-8 -*-

"""Post-migration for 17.0.5.2.0.

17.0.5.1.0 briefly modelled native TRX as a token preset with
sentinel ``contract_address = "_"``. 17.0.5.2.0 reverts that approach
in favour of a wallet-level ``sync_trx_transfers`` boolean on
``sca.watched_address`` (mirroring the existing ``sync_eth_transfers``
shape for ERC-20).

This migration:

  1. **Promotes** every existing ``sca.token`` row with
     ``contract_address = '_'`` into ``sync_trx_transfers = True`` on
     its parent ``sca.watched_address``, then unlinks the token row —
     so a user who already added TRX as a "token" gets the equivalent
     wallet-level setting auto-enabled.
  2. **Deletes** the seeded ``sca.token.preset`` row for TRX along
     with its ``ir.model.data`` xmlid, so the dropdown stops listing it.

Both steps are idempotent.
"""

NATIVE_SENTINEL = '_'


def migrate(cr, version):
    # Step 1: lift any user-created "TRX as a token" rows into the
    # wallet-level flag.
    cr.execute(
        "SELECT id, watched_address_id FROM sca_token "
        "WHERE contract_address = %s",
        (NATIVE_SENTINEL,),
    )
    rows = cr.fetchall()
    if rows:
        wallet_ids = list({r[1] for r in rows if r[1]})
        token_ids = [r[0] for r in rows]
        if wallet_ids:
            cr.execute(
                "UPDATE sca_watched_address "
                "   SET sync_trx_transfers = TRUE "
                " WHERE id IN %s",
                (tuple(wallet_ids),),
            )
        if token_ids:
            cr.execute(
                "DELETE FROM sca_token WHERE id IN %s",
                (tuple(token_ids),),
            )

    # Step 2: drop the 17.0.5.1.0 TRX preset record + its xmlid.
    cr.execute(
        "SELECT res_id FROM ir_model_data "
        " WHERE module = 'simple_crypto_accounting' "
        "   AND name   = 'preset_trc20_trx' "
        "   AND model  = 'sca.token.preset'"
    )
    res_ids = [r[0] for r in cr.fetchall()]
    if res_ids:
        cr.execute(
            "DELETE FROM sca_token_preset WHERE id IN %s",
            (tuple(res_ids),),
        )
        cr.execute(
            "DELETE FROM ir_model_data "
            " WHERE module = 'simple_crypto_accounting' "
            "   AND name   = 'preset_trc20_trx' "
            "   AND model  = 'sca.token.preset'"
        )
