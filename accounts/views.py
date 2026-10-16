from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.http import require_POST

from core import ratelimit as rl
from core.audit import audit
from core.utils import get_client_ip

from .forms import EmailAuthenticationForm, ProfileForm, RegistrationForm
from .models import User
from .tokens import email_verification_token


def send_verification_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    link = request.build_absolute_uri(reverse("accounts:verify_email", args=[uid, token]))
    body = render_to_string("accounts/email/verify_email.txt", {"user": user, "link": link, "site_name": settings.SITE_NAME})
    send_mail(f"Verify your {settings.SITE_NAME} account", body, settings.DEFAULT_FROM_EMAIL, [user.email])


@rl.ratelimit("register")
def register(request):
    if request.user.is_authenticated:
        return redirect("signals:dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.accepted_terms_at = timezone.now()
        user.save()
        audit("account.registered", actor=user, target=user, request=request)
        send_verification_email(request, user)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Account created. Check your email for a verification link to unlock your free signal.")
        return redirect("signals:dashboard")
    return render(request, "accounts/register.html", {"form": form})


class RateLimitedLoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        ip = get_client_ip(request)
        email = (request.POST.get("username") or "").strip().lower()
        if rl.is_limited("login", f"ip:{ip}") or (email and rl.is_limited("login", f"user:{email}")):
            audit("auth.login_blocked", request=request, email=email)
            form = self.get_form()
            form.add_error(None, "Too many failed login attempts. Please wait 15 minutes and try again.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        ip = get_client_ip(self.request)
        email = (self.request.POST.get("username") or "").strip().lower()
        rl.hit("login", f"ip:{ip}")
        if email:
            rl.hit("login", f"user:{email}")
        audit("auth.login_failed", request=self.request, email=email)
        return super().form_invalid(form)

    def form_valid(self, form):
        response = super().form_valid(form)
        rl.reset("login", f"user:{form.get_user().email}")
        audit("auth.login", request=self.request, target=form.get_user())
        return response


def verify_email(request, uidb64, token):
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None
    if user is None or not email_verification_token.check_token(user, token):
        messages.error(request, "This verification link is invalid or has expired.")
        return redirect("signals:dashboard" if request.user.is_authenticated else "accounts:login")
    if not user.is_verified:
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])
        audit("account.verified", actor=user, target=user, request=request)
    messages.success(request, "Your email is verified.")
    return redirect("signals:dashboard" if request.user.is_authenticated else "accounts:login")


@login_required
@require_POST
@rl.ratelimit("password_reset")
def resend_verification(request):
    if request.user.is_verified:
        messages.info(request, "Your email is already verified.")
    else:
        send_verification_email(request, request.user)
        messages.success(request, "Verification email sent.")
    return redirect("accounts:profile")


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit("account.profile_updated", request=request, target=request.user, changed=list(form.changed_data))
        messages.success(request, "Profile updated.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})


@method_decorator(rl.ratelimit("password_reset"), name="dispatch")
class RateLimitedPasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/email/password_reset_email.txt"
    subject_template_name = "accounts/email/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class AuditedPasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change_form.html"
    success_url = reverse_lazy("accounts:password_change_done")

    def form_valid(self, form):
        response = super().form_valid(form)
        audit("account.password_changed", request=self.request, target=self.request.user)
        return response
