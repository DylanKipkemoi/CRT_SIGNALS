from django.conf import settings


def site_context(request):
    return {
        "SITE_NAME": settings.SITE_NAME,
        "CONTACT_EMAIL": settings.CONTACT_EMAIL,
    }
