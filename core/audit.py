import logging

from .models import AuditLog
from .utils import get_client_ip

logger = logging.getLogger("audit")


def audit(action, *, actor=None, target=None, request=None, message="", **metadata):
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    if actor is None and request is not None and request.user.is_authenticated:
        actor = request.user
    entry = AuditLog.objects.create(
        actor=actor,
        action=action,
        target_type=target.__class__.__name__ if target is not None else "",
        target_id=str(getattr(target, "pk", "")) if target is not None else "",
        message=message[:255],
        metadata=metadata,
        ip_address=get_client_ip(request) if request is not None else None,
    )
    logger.info("audit action=%s actor=%s target=%s:%s", action, getattr(actor, "pk", None),
                entry.target_type, entry.target_id)
    return entry
