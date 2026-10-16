import re

from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from accounts.validators import normalize_kenyan_phone
from core.testing import make_user


class RegistrationTests(TestCase):
    def setUp(self):
        cache.clear()

    def data(self, **kw):
        d = {"full_name": "Jane Wanjiku", "email": "jane@example.com", "phone": "0712 345 678",
             "password1": "Very-Str0ng-Pass!", "password2": "Very-Str0ng-Pass!", "accept_terms": "on"}
        d.update(kw)
        return d

    def test_register_verify_and_login(self):
        r = self.client.post(reverse("accounts:register"), self.data())
        self.assertRedirects(r, reverse("signals:dashboard"))
        user = User.objects.get(email="jane@example.com")
        self.assertEqual(user.phone, "254712345678")
        self.assertFalse(user.is_verified)
        self.assertTrue(user.password.startswith("pbkdf2_"))
        link = re.search(r"https?://\S+", mail.outbox[0].body).group(0)
        self.client.get(link)
        user.refresh_from_db()
        self.assertTrue(user.is_verified)
        self.client.logout()
        r = self.client.post(reverse("accounts:login"), {"username": "jane@example.com", "password": "Very-Str0ng-Pass!"})
        self.assertEqual(r.status_code, 302)

    def test_duplicates_and_terms(self):
        make_user(email="jane@example.com", phone="254712345678")
        r = self.client.post(reverse("accounts:register"), self.data())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.filter(email="jane@example.com").count(), 1)
        r = self.client.post(reverse("accounts:register"), self.data(email="new@example.com"))
        self.assertFalse(User.objects.filter(email="new@example.com").exists())
        r = self.client.post(reverse("accounts:register"), self.data(email="x@example.com", phone="0799000111",
                                                                     accept_terms=""))
        self.assertFalse(User.objects.filter(email="x@example.com").exists())

    def test_password_mismatch(self):
        self.client.post(reverse("accounts:register"), self.data(password2="nope-Nope-123"))
        self.assertFalse(User.objects.exists())

    def test_phone_normalisation(self):
        for raw in ("0712345678", "+254712345678", "254712345678", "0112345678"):
            self.assertRegex(normalize_kenyan_phone(raw), r"^254[17]\d{8}$")
        from django.core.exceptions import ValidationError
        for bad in ("12345", "0812345678", "+15551234567"):
            with self.assertRaises(ValidationError):
                normalize_kenyan_phone(bad)

    def test_login_rate_limited(self):
        make_user(email="a@example.com")
        for _ in range(5):
            self.client.post(reverse("accounts:login"), {"username": "a@example.com", "password": "wrong"})
        r = self.client.post(reverse("accounts:login"), {"username": "a@example.com", "password": "wrong"})
        self.assertEqual(r.status_code, 429)

    def test_suspended_user_cannot_login(self):
        make_user(email="s@example.com", is_active=False)
        r = self.client.post(reverse("accounts:login"), {"username": "s@example.com", "password": "Str0ng-Passw0rd!"})
        self.assertEqual(r.status_code, 200)

    def test_protected_pages_require_login(self):
        for name in ("signals:dashboard", "payments:pay", "payments:history", "access:status", "accounts:profile"):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302, name)
        self.assertEqual(self.client.get(reverse("staff:dashboard")).status_code, 302)
        self.client.force_login(make_user())
        self.assertEqual(self.client.get(reverse("staff:dashboard")).status_code, 302)

    def test_password_reset_sends_email(self):
        make_user(email="r@example.com")
        self.client.post(reverse("accounts:password_reset"), {"email": "r@example.com"})
        self.assertEqual(len(mail.outbox), 1)


class PagesTests(TestCase):
    def test_public_pages_and_mobile_viewport(self):
        for name in ("core:home", "core:terms", "core:risk", "core:privacy", "core:contact", "markets:overview",
                     "accounts:login", "accounts:register"):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)
            self.assertContains(r, 'name="viewport"')
            self.assertContains(r, "Risk warning")
        r = self.client.get(reverse("core:home"))
        self.assertIn("Content-Security-Policy", r.headers)
        self.assertNotContains(r, "guaranteed win")

    def test_staff_dashboard_and_manual_scan(self):
        staff = make_user(staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("staff:dashboard")).status_code, 200)
