# M-Pesa Daraja (STK Push / Lipa Na M-Pesa Online)

Reference: https://developer.safaricom.co.ke (APIs → *M-Pesa Express*, *Authorization*, *M-Pesa Express Query*). Check the portal for current endpoint versions before going live.

## Sandbox setup
1. Create an account at https://developer.safaricom.co.ke and create an app with **M-Pesa Express** (sandbox).
2. Copy the app's **Consumer Key** and **Consumer Secret**. From *Test credentials*, copy the sandbox **Business Shortcode** (commonly `174379`) and the **Passkey**.
3. Expose a public **HTTPS** URL for your dev server, e.g. `ngrok http 8000`, and add the host to `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`.
4. Set these in `.env`:
```
DARAJA_ENVIRONMENT=sandbox
DARAJA_CONSUMER_KEY=...
DARAJA_CONSUMER_SECRET=...
DARAJA_SHORTCODE=174379
DARAJA_PASSKEY=...
DARAJA_TRANSACTION_TYPE=CustomerPayBillOnline     # CustomerBuyGoodsOnline for till numbers
DARAJA_CALLBACK_BASE_URL=https://<your-ngrok-host>
DARAJA_CALLBACK_TOKEN=<long random string>        # python -c "import secrets;print(secrets.token_urlsafe(32))"
DARAJA_VERIFY_WITH_QUERY=true
```
5. Restart the server, log in as a verified user who has used their free signal, open **Unlock today**, and enter a sandbox test MSISDN. Approve the prompt on the simulator or test phone.

## How it works
1. `payments.services.initiate_payment` checks for a verified user, no active access, and no open payment. It creates a `PaymentTransaction` (pending, unique reference), then calls `POST /mpesa/stkpush/v1/processrequest` with an OAuth token from `GET /oauth/v1/generate?grant_type=client_credentials`. Password = Base64(Shortcode + Passkey + Timestamp).
2. Safaricom POSTs the result to `/payments/mpesa/callback/<DARAJA_CALLBACK_TOKEN>/`. A wrong token returns 403. `DARAJA_ALLOWED_CALLBACK_IPS` optionally restricts source IPs (Safaricom publishes its callback IP ranges).
3. The callback is validated, its payload sanitised (phone masked) and logged, then correlated by `CheckoutRequestID` + `MerchantRequestID`. `ResultCode 0` with matching amount, plus (when `DARAJA_VERIFY_WITH_QUERY=true`) a confirming `POST /mpesa/stkpushquery/v1/query`, marks the payment success and grants `DailySignalAccess` in one transaction. 1032 → cancelled, 1037 → timed out, others → failed. Duplicate or late callbacks change nothing.
4. The browser only polls `/payments/api/status/<reference>/`, which reads the database. A frontend message can never grant access.
5. `python manage.py reconcile_payments` (also run by `run_scanner`) queries payments still pending after `DARAJA_PENDING_TIMEOUT_SECONDS`.

The website never asks for, sees, or stores the M-Pesa PIN. The user enters it on their own phone.

## Going live
Complete Safaricom's Go-Live process for your shortcode. Then set `DARAJA_ENVIRONMENT=production` (base URL `https://api.safaricom.co.ke`), production credentials, a production HTTPS callback domain, and a fresh callback token. Amount mismatches and failed verifications are flagged `needs_review` in admin.
