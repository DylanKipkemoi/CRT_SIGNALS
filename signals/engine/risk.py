"""Risk/reward helpers with direction-aware validation."""


class InvalidLevels(ValueError):
    pass


def risk_reward(direction, entry, stop, target):
    """R multiple for a BUY or SELL. Raises InvalidLevels if levels are inconsistent."""
    if direction == "BUY":
        risk, reward = entry - stop, target - entry
    elif direction == "SELL":
        risk, reward = stop - entry, entry - target
    else:
        raise InvalidLevels(f"Unknown direction {direction!r}")
    if risk <= 0:
        raise InvalidLevels("Stop loss is on the wrong side of entry.")
    if reward <= 0:
        raise InvalidLevels("Target is on the wrong side of entry.")
    return reward / risk


def validate_levels(direction, entry_low, entry_high, stop, targets):
    if entry_low > entry_high:
        raise InvalidLevels("Entry zone low is above entry zone high.")
    if not targets:
        raise InvalidLevels("At least one take-profit target is required.")
    if direction == "BUY":
        if not stop < entry_low:
            raise InvalidLevels("BUY stop loss must be below the entry zone.")
        if any(t <= entry_high for t in targets):
            raise InvalidLevels("BUY targets must be above the entry zone.")
        if targets != sorted(targets):
            raise InvalidLevels("BUY targets must be ascending.")
    elif direction == "SELL":
        if not stop > entry_high:
            raise InvalidLevels("SELL stop loss must be above the entry zone.")
        if any(t >= entry_low for t in targets):
            raise InvalidLevels("SELL targets must be below the entry zone.")
        if targets != sorted(targets, reverse=True):
            raise InvalidLevels("SELL targets must be descending.")
    else:
        raise InvalidLevels(f"Unknown direction {direction!r}")
