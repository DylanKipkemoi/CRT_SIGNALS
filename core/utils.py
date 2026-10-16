import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

NAIROBI = ZoneInfo("Africa/Nairobi")


def now_nairobi():
    return timezone.now().astimezone(NAIROBI)


def nairobi_date(dt=None):
    dt = dt or timezone.now()
    return dt.astimezone(NAIROBI).date()


def day_bounds_nairobi(day, end_time=None):
    """Return (start, end) aware datetimes for a Nairobi calendar day.

    ``end`` is exclusive. When ``end_time`` (a ``datetime.time``) is given the
    access window ends at that local time, rounded up to the next second so
    23:59:59 means "until midnight".
    """
    start = datetime.datetime.combine(day, datetime.time.min, tzinfo=NAIROBI)
    if end_time is None:
        end = start + datetime.timedelta(days=1)
    else:
        end = datetime.datetime.combine(day, end_time, tzinfo=NAIROBI) + datetime.timedelta(seconds=1)
        end = end.replace(microsecond=0)
    return start, end


def get_client_ip(request):
    """Client IP honoring only the configured number of trusted proxies."""
    proxies = getattr(settings, "TRUSTED_PROXY_COUNT", 0)
    remote = request.META.get("REMOTE_ADDR", "")
    if proxies > 0:
        forwarded = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
        if len(forwarded) >= proxies:
            return forwarded[-proxies]
    return remote or None


def mask_phone(phone):
    phone = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if len(phone) < 7:
        return "*" * len(phone)
    return f"{phone[:5]}***{phone[-3:]}"
