# -*- coding: utf-8 -*-

"""Post-migration for 17.0.5.0.1.

Corrects the seeded USDT-TRC20 preset contract address that was
mis-entered in 17.0.3.1.0 / 17.0.5.0.0 (the seed file had
``TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj`` which is NOT USDT; the
canonical contract is ``TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t``).

Because the preset data file declares ``noupdate="1"`` (to preserve
user edits across upgrades), the new XML value would otherwise not
overwrite the existing DB row. This migration fixes:

  1. The ``sca.token.preset`` record itself.
  2. Any ``sca.token`` rows the user already created using the bogus
     value — they're updated in place so the watched-token list reflects
     the canonical contract.

Both updates are idempotent; rerunning is safe.
"""

WRONG_USDT_CONTRACT = 'TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj'
RIGHT_USDT_CONTRACT = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'


def migrate(cr, version):
    cr.execute(
        """
        UPDATE sca_token_preset
           SET contract_address = %s
         WHERE network = 'trc20'
           AND symbol = 'USDT'
           AND contract_address = %s
        """,
        (RIGHT_USDT_CONTRACT, WRONG_USDT_CONTRACT),
    )
    cr.execute(
        """
        UPDATE sca_token
           SET contract_address = %s
         WHERE contract_address = %s
        """,
        (RIGHT_USDT_CONTRACT, WRONG_USDT_CONTRACT),
    )
