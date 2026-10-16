"""Small cache-backed fixed-window rate limiter."""

import functools
import hashlib

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse

from .utils import get_client_ip


def parse_rate(rate):
    count, window = str(rate).split("/")
    return int(count), int(window)


def _key(scope, ident):
    digest = hashlib.sha256(str(ident).encode()).hexdigest()[:32]
    return f"rl:{scope}:{digest}"


def hit(scope, ident, rate=None):
    """Record a hit. Returns True if the limit is now exceeded."""
    limit, window = parse_rate(rate or settings.RATE_LIMITS[scope])
    key = _key(scope, ident)
    cache.add(key, 0, window)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, window)
        count = 1
    return count > limit


def is_limited(scope, ident, rate=None):
    limit, _ = parse_rate(rate or settings.RATE_LIMITS[scope])
    return (cache.get(_key(scope, ident)) or 0) >= limit


def reset(scope, ident):
    cache.delete(_key(scope, ident))


def ratelimit(scope, methods=("POST",), key=None, json=False):
    """Decorator limiting requests per client IP (or a custom key function)."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method in methods:
                ident = key(request) if key else get_client_ip(request)
                if hit(scope, ident):
                    msg = "Too many requests. Please wait and try again."
                    if json:
                        return JsonResponse({"error": msg}, status=429)
                    return HttpResponse(msg, status=429, content_type="text/plain")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
