import re

from django.core.exceptions import ValidationError

_KENYAN = re.compile(r"^(?:\+?254|0)?([17]\d{8})$")


def normalize_kenyan_phone(value):
    """Normalize Kenyan mobile numbers to the 2547XXXXXXXX / 2541XXXXXXXX form.

    Accepts 07XXXXXXXX, 01XXXXXXXX, 7XXXXXXXX, +2547XXXXXXXX and 2547XXXXXXXX
    (spaces and dashes are ignored). Raises ValidationError otherwise.
    """
    cleaned = re.sub(r"[\s\-()]", "", str(value or ""))
    match = _KENYAN.match(cleaned)
    if not match:
        raise ValidationError("Enter a valid Kenyan mobile number, e.g. 0712345678 or +254712345678.")
    return f"254{match.group(1)}"
