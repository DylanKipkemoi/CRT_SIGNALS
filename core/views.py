from django.conf import settings
from django.contrib import messages
from django.core.mail import mail_admins
from django.shortcuts import redirect, render

from .forms import ContactForm
from .models import SiteConfiguration
from .ratelimit import ratelimit


def home(request):
    from signals.services import performance_stats

    config = SiteConfiguration.load()
    return render(request, "core/home.html", {"config": config, "stats": performance_stats()})


def terms(request):
    return render(request, "core/terms.html")


def risk_disclosure(request):
    return render(request, "core/risk.html")


def privacy(request):
    return render(request, "core/privacy.html")


@ratelimit("contact")
def contact(request):
    initial = {}
    if request.user.is_authenticated:
        initial = {"name": request.user.full_name, "email": request.user.email}
    form = ContactForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        msg = form.save(commit=False)
        if request.user.is_authenticated:
            msg.user = request.user
        msg.save()
        mail_admins(f"[{settings.SITE_NAME}] Contact: {msg.subject}", f"From {msg.name} <{msg.email}>\n\n{msg.message}",
                    fail_silently=True)
        messages.success(request, "Thanks — your message has been received.")
        return redirect("core:contact")
    return render(request, "core/contact.html", {"form": form})
