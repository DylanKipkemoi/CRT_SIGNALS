from dataclasses import asdict, dataclass, field, fields

from core.models import DEFAULT_SCORE_WEIGHTS


@dataclass
class EngineConfig:
    # Swings / structure
    swing_lookback_htf: int = 3          # bars each side for a 1H pivot
    swing_lookback_ltf: int = 2          # bars each side for a 5M/15M pivot
    atr_period: int = 14
    # Displacement: body >= mult * ATR and body/range >= ratio
    displacement_atr_mult: float = 1.2
    displacement_body_ratio: float = 0.6
    # FVG must be at least this fraction of ATR to count
    fvg_min_atr_frac: float = 0.15
    # CRT sweep depth bounds as a fraction of the reference candle range
    crt_min_sweep_frac: float = 0.03
    crt_max_sweep_frac: float = 0.75
    # Reference candle must be at least this multiple of the 1H ATR
    crt_min_range_atr: float = 0.5
    # How many most-recent (reference, manipulation) 1H pairs to evaluate
    crt_lookback_pairs: int = 2
    # Equal highs/lows tolerance (fraction of ATR)
    equal_level_atr_frac: float = 0.1
    # Stop buffer beyond the sweep extreme (fraction of LTF ATR)
    stop_buffer_atr_frac: float = 0.25
    # Reject entries further than this many 1H ATRs from the current price
    max_entry_distance_atr: float = 1.5
    # Reject stops wider than this many 1H ATRs
    max_stop_atr: float = 2.5
    min_risk_reward: float = 2.0
    a_plus_threshold: int = 80
    require_order_flow: bool = False
    order_flow_unavailable_credit: int = 0
    weights: dict = field(default_factory=lambda: dict(DEFAULT_SCORE_WEIGHTS))
    confirmation_timeframe: str = "5m"
    allow_provisional: bool = True

    @classmethod
    def from_site_config(cls, site):
        cfg = cls(
            min_risk_reward=float(site.min_risk_reward),
            a_plus_threshold=site.a_plus_threshold,
            require_order_flow=site.require_order_flow,
            order_flow_unavailable_credit=site.order_flow_unavailable_credit,
            weights=dict(site.score_weights),
            allow_provisional=site.allow_provisional_signals,
        )
        valid = {f.name for f in fields(cls)}
        for key, value in (site.engine_overrides or {}).items():
            if key in valid and key != "weights":
                setattr(cfg, key, type(getattr(cfg, key))(value))
        return cfg

    def as_dict(self):
        return asdict(self)
