import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from access.models import DailySignalAccess, FreeSignalEntitlement, SignalUnlock
from access.services import (AccessDenied, active_daily_access, can_view_signal, grant_daily_access,
                             use_free_signal)
from core.testing import make_signal, make_user
from core.utils import nairobi_date


class FreeSignalTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.s1 = make_signal()
        self.s2 = make_signal(direction="SELL")

    def test_free_signal_once_only(self):
        self.assertFalse(can_view_signal(self.user, self.s1))
        self.assertTrue(use_free_signal(self.user, self.s1))
        self.assertTrue(can_view_signal(self.user, self.s1))
        with self.assertRaises(AccessDenied):
            use_free_signal(self.user, self.s2)
        self.assertFalse(can_view_signal(self.user, self.s2))
        ent = FreeSignalEntitlement.objects.get(user=self.user)
        self.assertEqual((ent.used, ent.remaining), (1, 0))

    def test_reusing_on_same_signal_does_not_consume_again(self):
        use_free_signal(self.user, self.s1)
        self.assertFalse(use_free_signal(self.user, self.s1))
        self.assertEqual(FreeSignalEntitlement.objects.get(user=self.user).used, 1)

    def test_persists_across_sessions_and_logout(self):
        self.client.force_login(self.user)
        self.client.post(reverse("signals:unlock_free", args=[self.s1.pk]))
        self.client.logout()
        self.client.force_login(self.user)
        r = self.client.get(reverse("signals:detail", args=[self.s1.pk]))
        self.assertContains(r, "Trade plan")
        self.client.post(reverse("signals:unlock_free", args=[self.s2.pk]))
        r = self.client.get(reverse("signals:detail", args=[self.s2.pk]))
        self.assertContains(r, "This signal is locked")
        self.assertNotContains(r, "1016.65")
        self.assertEqual(SignalUnlock.objects.filter(user=self.user).count(), 1)

    def test_unverified_cannot_use_free(self):
        user = make_user(verified=False)
        with self.assertRaises(AccessDenied):
            use_free_signal(user, self.s1)

    def test_provisional_not_eligible(self):
        prov = make_signal(is_provisional=True, status="provisional")
        with self.assertRaises(AccessDenied):
            use_free_signal(self.user, prov)

    def test_locked_detail_hides_levels(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("signals:detail", args=[self.s1.pk]))
        self.assertContains(r, "Use my free signal")
        self.assertNotContains(r, "983.35")
        chart = self.client.get(reverse("signals:chart_data", args=["BTCUSD"]) + f"?signal={self.s1.pk}").json()
        self.assertEqual(chart["levels"], [])


class DailyAccessTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_daily_access_unlocks_today_and_expires_at_nairobi_midnight(self):
        now = timezone.now()
        access, created = grant_daily_access(self.user, now=now)
        self.assertTrue(created)
        self.assertEqual(access.access_date, nairobi_date(now))
        local_exp = timezone.localtime(access.expires_at)
        self.assertEqual(local_exp.date(), nairobi_date(now) + datetime.timedelta(days=1))
        self.assertEqual((local_exp.hour, local_exp.minute), (0, 0))
        sig = make_signal()
        self.assertTrue(can_view_signal(self.user, sig, now=now))
        self.assertIsNone(active_daily_access(self.user, access.expires_at + datetime.timedelta(seconds=1)))
        later = make_signal(created_at=access.expires_at + datetime.timedelta(hours=1))
        self.assertFalse(can_view_signal(self.user, later, now=access.expires_at + datetime.timedelta(hours=1)))
        self.assertTrue(can_view_signal(self.user, sig, now=access.expires_at + datetime.timedelta(hours=1)),
                        "signals viewed during paid access stay in history")

    def test_grant_is_idempotent_per_day(self):
        now = timezone.now()
        grant_daily_access(self.user, now=now)
        _, created = grant_daily_access(self.user, now=now)
        self.assertFalse(created)
        self.assertEqual(DailySignalAccess.objects.filter(user=self.user).count(), 1)

    def test_status_page(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("access:status"))
        self.assertContains(r, "Free signal")
