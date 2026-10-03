from hashlib import sha256

from django.core.cache import cache


_RATE_LIMITS = {
    "login": {"ip": (30, 900), "identity": (5, 900)},
    "signup": {"ip": (5, 3600), "identity": (3, 3600)},
    "verification_resend": {"ip": (5, 3600), "identity": (3, 3600)},
    "password_reset": {"ip": (10, 3600), "identity": (3, 3600)},
}


def _increment(key, window):
    if cache.add(key, 1, timeout=window):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.add(key, 1, timeout=window)
        return 1


def is_rate_limited(request, scope, identity=""):
    limits = _RATE_LIMITS[scope]
    remote_addr = request.META.get("REMOTE_ADDR", "unknown")
    dimensions = [("ip", remote_addr, *limits["ip"])]
    if identity:
        dimensions.append(("identity", identity.strip().casefold(), *limits["identity"]))

    is_limited = False
    for dimension, value, maximum, window in dimensions:
        digest = sha256(value.encode("utf-8", errors="replace")).hexdigest()
        key = f"auth-rate:{scope}:{dimension}:{digest}"
        is_limited = _increment(key, window) > maximum or is_limited
    return is_limited


def retry_after(scope):
    return max(window for maximum, window in _RATE_LIMITS[scope].values())
