-- Upwork rotates the refresh token: whoever refreshes last owns the grant and
-- every other holder gets `invalid_grant`. A copy of production carrying live
-- tokens therefore steals the grant from production on its first cron tick,
-- sync, 401 retry or click of "Refresh Token Now" — so a neutralized copy must
-- come up disconnected. Reconnect it against a separate Upwork app if needed.
UPDATE usa_settings
   SET access_token = NULL,
       refresh_token = NULL,
       token_expiry = NULL,
       token_last_refresh = NULL,
       token_last_error = NULL,
       token_reconnect_notified = FALSE;
