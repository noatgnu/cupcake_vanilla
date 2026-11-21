from django.conf import settings


def frontend_base_url(request=None):
    """
    Address of the frontend a request came from when it is an allowed origin, otherwise FRONTEND_URL, otherwise the
    first allowed origin.
    """
    allowed = [origin.rstrip("/") for origin in getattr(settings, "CORS_ORIGIN_WHITELIST", []) if origin]
    origin = (request.META.get("HTTP_ORIGIN") or "").rstrip("/") if request is not None else ""
    if origin and origin in allowed:
        return origin
    configured = (getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")
    if configured:
        return configured
    return allowed[0] if allowed else "http://localhost:4200"


def frontend_link(request, route):
    """Absolute link to a hash-routed frontend page, such as "lab-groups/invitations/1/accept"."""
    return f"{frontend_base_url(request)}/#/{route.lstrip('/')}"
