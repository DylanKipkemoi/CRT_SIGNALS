from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def price(value, digits=2):
    if value is None or value == "":
        return "—"
    try:
        return f"{Decimal(str(value)):,.{int(digits)}f}"
    except (InvalidOperation, ValueError):
        return value


@register.filter
def direction_class(direction):
    return {"BUY": "text-bull", "SELL": "text-bear"}.get(str(direction), "text-muted-2")


@register.filter
def direction_badge(direction):
    return {"BUY": "badge-buy", "SELL": "badge-sell", "WAIT": "badge-wait"}.get(str(direction), "badge-notrade")


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None
