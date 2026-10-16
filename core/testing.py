"""Shared test factories."""

import datetime
import itertools
from decimal import Decimal

from django.utils import timezone

from markets.models import MarketInstrument

_seq = itertools.count(1)


def make_user(verified=True, staff=False, **kw):
    from accounts.models import User

    n = next(_seq)
    user = User.objects.create_user(
        email=kw.pop("email", f"user{n}@example.com"), password=kw.pop("password", "Str0ng-Passw0rd!"),
        full_name=kw.pop("full_name", f"Test User {n}"), phone=kw.pop("phone", f"25471{n:07d}"), **kw)
    if verified:
        user.email_verified_at = timezone.now()
    user.is_staff = staff
    user.save()
    return user


def make_signal(symbol="BTCUSD", direction="BUY", created_at=None, **kw):
    from signals.models import TradingSignal

    inst = MarketInstrument.objects.get(symbol=symbol)
    created_at = created_at or timezone.now()
    n = next(_seq)
    if direction == "BUY":
        levels = dict(entry_low=Decimal("992"), entry_high=Decimal("994.5"), entry_price=Decimal("993.25"),
                      stop_loss=Decimal("983.35"), take_profit_1=Decimal("1012"), take_profit_2=Decimal("1030"),
                      take_profit_3=Decimal("1035"))
    else:
        levels = dict(entry_low=Decimal("1005.5"), entry_high=Decimal("1008"), entry_price=Decimal("1006.75"),
                      stop_loss=Decimal("1016.65"), take_profit_1=Decimal("988"), take_profit_2=Decimal("970"),
                      take_profit_3=Decimal("965"))
    data = dict(
        instrument=inst, direction=direction, score=90, score_breakdown={}, classification="A+",
        setup_type="CRT test", risk_reward=Decimal("4.22"), risk_reward_tp1=Decimal("1.89"),
        ref_candle_open=created_at - datetime.timedelta(hours=2), ref_high=Decimal("1012"), ref_low=Decimal("990"),
        ref_mid=Decimal("1001"), order_flow_status="unavailable", provider="test", provider_symbol="TEST",
        explanation="test", invalidation_conditions="test", setup_key=f"test-{n}", created_at=created_at,
        expires_at=created_at + datetime.timedelta(hours=8),
    )
    data.update(levels)
    data.update(kw)
    return TradingSignal.objects.create(**data)
