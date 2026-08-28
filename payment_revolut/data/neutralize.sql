-- disable revolut payment provider
UPDATE payment_provider
   SET revolut_secret_key = NULL,
       revolut_webhook_secret = NULL
 WHERE code = 'revolut';
