"""Access control: one-time free signal + paid Nairobi-day access."""

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.audit import audit
from core.models import SiteConfiguration
from core.utils import day_bounds_nairobi, nairobi_date
from signals.models import OPEN_STATUSES, SignalStatus

from .models import DailySignalAccess, FreeSignalEntitlement, SignalUnlock


class AccessDenied(Exception):
    pass


def get_entitlement(user):
    ent, _ = FreeSignalEntitlement.objects.get_or_create(
        user=user, defaults={"allowance": SiteConfiguration.load().free_signals_per_user}
    )
    return ent


def active_daily_access(user, now=None):
    now = now or timezone.now()
    return DailySignalAccess.objects.filter(user=user, starts_at__lte=now, expires_at__gt=now).first()


def has_unlock(user, signal):
    return SignalUnlock.objects.filter(user=user, signal=signal).exists()


def signal_covered_by_access(signal, access):
    start, end = access.starts_at, access.expires_at
    created_today = nairobi_date(signal.created_at) == access.access_date
    still_open = signal.status in OPEN_STATUSES and signal.created_at < end
    return created_today or still_open or (start <= signal.created_at < end)


def can_view_signal(user, signal, now=None, record=True):
    """True if the user may see full signal details. Records paid views for history."""
    if not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    if has_unlock(user, signal):
        return True
    access = active_daily_access(user, now)
    if access and signal_covered_by_access(signal, access):
        if record:
            SignalUnlock.objects.get_or_create(
                user=user, signal=signal, defaults={"source": SignalUnlock.Source.PAID, "daily_access": access}
            )
        return True
    return False


def free_signal_eligible(signal):
    return (
        signal.classification == "A+" and not signal.is_provisional
        and signal.status not in (SignalStatus.PROVISIONAL, SignalStatus.SUPERSEDED)
    )


def use_free_signal(user, signal, request=None):
    """Consume the user's free entitlement on ``signal`` exactly once."""
    if not user.is_verified:
        raise AccessDenied("Verify your email address before using your free signal.")
    if not free_signal_eligible(signal):
        raise AccessDenied("Only confirmed A+ signals can be unlocked with the free signal.")
    if has_unlock(user, signal):
        return False
    get_entitlement(user)
    with transaction.atomic():
        ent = FreeSignalEntitlement.objects.select_for_update().get(user=user)
        if ent.remaining <= 0:
            raise AccessDenied("Your free signal has already been used. Unlock today's signals for full access.")
        try:
            with transaction.atomic():
                SignalUnlock.objects.create(user=user, signal=signal, source=SignalUnlock.Source.FREE)
        except IntegrityError:
            return False
        ent.used += 1
        ent.consumed_at = timezone.now()
        ent.save(update_fields=["used", "consumed_at"])
    audit("access.free_signal_used", actor=user, target=signal, request=request)
    return True


def access_window(day=None):
    site = SiteConfiguration.load()
    day = day or nairobi_date()
    return day_bounds_nairobi(day, site.daily_access_end_time)


def grant_daily_access(user, *, payment=None, granted_by=None, now=None, request=None):
    """Create today's access row. Returns (access, created)."""
    now = now or timezone.now()
    day = nairobi_date(now)
    start, end = access_window(day)
    if now >= end:
        # Paid after the configured end time: access applies to the next Nairobi day.
        from datetime import timedelta

        day = day + timedelta(days=1)
        start, end = access_window(day)
    try:
        with transaction.atomic():
            access = DailySignalAccess.objects.create(
                user=user, access_date=day, starts_at=min(start, now) if now < end else start, expires_at=end,
                source=DailySignalAccess.Source.PAYMENT if payment else DailySignalAccess.Source.ADMIN,
                payment=payment, granted_by=granted_by,
            )
    except IntegrityError:
        return DailySignalAccess.objects.get(user=user, access_date=day), False
    audit("access.daily_granted", actor=granted_by or user, target=access, request=request,
          access_date=str(day), payment=str(payment.reference) if payment else None)
    return access, True


def access_summary(user, now=None):
    if not user.is_authenticated:
        return None
    ent = get_entitlement(user)
    access = active_daily_access(user, now)
    return {
        "free_remaining": ent.remaining,
        "free_allowance": ent.allowance,
        "free_used_at": ent.consumed_at,
        "free_signal": SignalUnlock.objects.filter(user=user, source=SignalUnlock.Source.FREE).select_related(
            "signal__instrument").first(),
        "daily_access": access,
        "has_paid_access": access is not None,
        "verified": user.is_verified,
        "fee": SiteConfiguration.load().daily_fee_kes,
    }
