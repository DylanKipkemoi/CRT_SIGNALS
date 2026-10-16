# Deployment & security

## Production checklist
- `DJANGO_DEBUG=false`, and a long random `DJANGO_SECRET_KEY` (startup fails without one).
- `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, and `SITE_URL` set to your HTTPS domain.
- PostgreSQL: `DATABASE_ENGINE=django.db.backends.postgresql`, `DATABASE_NAME/USER/PASSWORD/HOST/PORT`, plus `pip install "psycopg[binary]"`.
- A real SMTP `EMAIL_BACKEND` + `EMAIL_HOST*` so verification and reset emails are delivered.
- Behind a TLS-terminating proxy, set `USE_X_FORWARDED_PROTO=true` and `TRUSTED_PROXY_COUNT=<number of proxies>`. HTTPS redirect, HSTS, secure/HttpOnly cookies, CSP, `X-Frame-Options: DENY`, nosniff, and same-origin referrer/COOP are on when DEBUG is off.
- Use a shared cache (Redis/Memcached) when running more than one process, because the rate limiter, scanner lock and Daraja token cache use Django's cache.
- Run `python manage.py check --deploy`.

## Commands
```bash
pip install -r requirements.txt gunicorn
python manage.py migrate
python manage.py collectstatic --noinput
gunicorn config.wsgi --bind 0.0.0.0:8000 --workers 3
```
(On Windows servers use `waitress-serve --port=8000 config.wsgi:application`.)

## Scheduler (pick one)
- **systemd service**: `ExecStart=/srv/crt/.venv/bin/python manage.py run_scanner` with `Restart=always`.
- **cron**: `*/5 * * * * cd /srv/crt && .venv/bin/python manage.py scan_markets && .venv/bin/python manage.py reconcile_payments`
- **Windows Task Scheduler**: every 5 minutes run `C:\crt\.venv\Scripts\python.exe C:\crt\manage.py scan_markets`.
The scanner holds a cache lock, so overlapping runs are skipped. Scanner health (last run age vs `SCANNER_HEALTHY_MAX_AGE_SECONDS`) is shown on `/staff/`.

## Security notes
- Secrets come only from environment variables. `.env` is git-ignored. Daraja credentials never reach templates or JavaScript.
- Passwords use Django's PBKDF2 hasher and validators. Logins are rate-limited per IP+email. Admins can suspend users (`is_active`).
- Payment state changes only through verified callbacks or STK Query, never from the browser. All grants, payments, unlocks and admin actions are written to `AuditLog`.
- Signal scores, payment statuses and access grants are read-only for ordinary users. Signal records are read-only in admin.
- Logs mask phone numbers. Callback payloads are sanitised before storage.
