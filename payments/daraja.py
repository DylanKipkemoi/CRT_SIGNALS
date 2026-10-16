"""Safaricom Daraja M-Pesa Express (STK Push) client.

Endpoints (Daraja v1, per developer.safaricom.co.ke):
  OAuth:      GET  {base}/oauth/v1/generate?grant_type=client_credentials  (HTTP Basic key:secret)
  STK Push:   POST {base}/mpesa/stkpush/v1/processrequest
  STK Query:  POST {base}/mpesa/stkpushquery/v1/query
Password = base64(BusinessShortCode + Passkey + Timestamp), Timestamp = YYYYMMDDHHMMSS (EAT).
"""

import base64
import logging

import requests
from django.conf import settings
from django.core.cache import cache

from core.utils import now_nairobi

logger = logging.getLogger(__name__)

BASE_URLS = {"sandbox": "https://sandbox.safaricom.co.ke", "production": "https://api.safaricom.co.ke"}


class DarajaError(Exception):
    def __init__(self, message, code="", status=None, payload=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.payload = payload or {}


class DarajaNotConfigured(DarajaError):
    pass


class DarajaClient:
    def __init__(self, config=None):
        self.config = config or settings.DARAJA
        env = self.config["ENVIRONMENT"]
        if env not in BASE_URLS:
            raise DarajaNotConfigured("DARAJA_ENVIRONMENT must be 'sandbox' or 'production'.")
        self.base_url = BASE_URLS[env]
        self.timeout = self.config["HTTP_TIMEOUT"]

    def check_configured(self):
        missing = [k for k in ("CONSUMER_KEY", "CONSUMER_SECRET", "SHORTCODE", "PASSKEY", "CALLBACK_BASE_URL",
                               "CALLBACK_TOKEN") if not self.config.get(k)]
        if missing:
            raise DarajaNotConfigured("M-Pesa is not configured. Missing: " + ", ".join(f"DARAJA_{m}" for m in missing))
        if not self.config["CALLBACK_BASE_URL"].startswith("https://"):
            raise DarajaNotConfigured("DARAJA_CALLBACK_BASE_URL must be a public HTTPS URL.")

    @property
    def callback_url(self):
        return f"{self.config['CALLBACK_BASE_URL'].rstrip('/')}/payments/mpesa/callback/{self.config['CALLBACK_TOKEN']}/"

    def access_token(self):
        key = f"daraja:token:{self.config['ENVIRONMENT']}"
        token = cache.get(key)
        if token:
            return token
        try:
            resp = requests.get(
                f"{self.base_url}/oauth/v1/generate", params={"grant_type": "client_credentials"},
                auth=(self.config["CONSUMER_KEY"], self.config["CONSUMER_SECRET"]), timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DarajaError(f"OAuth request failed: {exc.__class__.__name__}") from exc
        if resp.status_code != 200:
            raise DarajaError("Daraja authentication failed.", status=resp.status_code)
        data = resp.json()
        token = data["access_token"]
        cache.set(key, token, max(int(data.get("expires_in", 3599)) - 60, 60))
        return token

    def _password(self):
        ts = now_nairobi().strftime("%Y%m%d%H%M%S")
        raw = f"{self.config['SHORTCODE']}{self.config['PASSKEY']}{ts}".encode()
        return base64.b64encode(raw).decode(), ts

    def _post(self, path, body):
        headers = {"Authorization": f"Bearer {self.access_token()}", "Content-Type": "application/json"}
        try:
            resp = requests.post(f"{self.base_url}{path}", json=body, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise DarajaError(f"Daraja request failed: {exc.__class__.__name__}") from exc
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code != 200:
            raise DarajaError(data.get("errorMessage") or f"Daraja HTTP {resp.status_code}",
                              code=data.get("errorCode", ""), status=resp.status_code, payload=data)
        return data

    def stk_push(self, phone, amount, account_reference, description):
        self.check_configured()
        password, ts = self._password()
        body = {
            "BusinessShortCode": self.config["SHORTCODE"],
            "Password": password,
            "Timestamp": ts,
            "TransactionType": self.config["TRANSACTION_TYPE"],
            "Amount": int(amount),
            "PartyA": phone,
            "PartyB": self.config.get("PARTY_B") or self.config["SHORTCODE"],
            "PhoneNumber": phone,
            "CallBackURL": self.callback_url,
            "AccountReference": account_reference[:12],
            "TransactionDesc": description[:13],
        }
        data = self._post("/mpesa/stkpush/v1/processrequest", body)
        if str(data.get("ResponseCode")) != "0":
            raise DarajaError(data.get("ResponseDescription") or "STK push rejected", code=str(data.get("ResponseCode")),
                              payload=data)
        return data

    def stk_query(self, checkout_request_id):
        self.check_configured()
        password, ts = self._password()
        return self._post("/mpesa/stkpushquery/v1/query", {
            "BusinessShortCode": self.config["SHORTCODE"],
            "Password": password,
            "Timestamp": ts,
            "CheckoutRequestID": checkout_request_id,
        })
