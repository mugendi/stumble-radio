"""Discovery preferences and the small, explicit rules behind adaptive shuffle."""

import math
import random
from dataclasses import dataclass

from .models import Search

POOL_MODES = ("Anywhere", "Music-only", "Talk/News", "Your language", "Nearby", "Hidden gems")
GEM_VOTES = 10
GEM_CLICKS = 15
DAYPART_BATCH = 64
QUICK_SKIP_SECONDS = 10
HOT_SECONDS = 60
SKIP_COOLDOWN = 24 * 3600
DEAD_COOLDOWN = 15 * 60
MAX_RECOVERY_ATTEMPTS = 8


@dataclass(frozen=True)
class DiscoverySettings:
    language: str = ""
    latitude: float | None = None
    longitude: float | None = None
    radius_km: float = 100
    recovery_seconds: int = 12

    def __post_init__(self):
        if not 3 <= self.recovery_seconds <= 120:
            raise ValueError("Recovery timeout must be between 3 and 120 seconds.")
        if self.latitude is not None or self.longitude is not None:
            Search(latitude=self.latitude, longitude=self.longitude, radius_km=self.radius_km)
        elif not math.isfinite(self.radius_km) or self.radius_km <= 0:
            raise ValueError("Radius must be positive and finite.")


def shuffle_key(seconds: float) -> float:
    """An exponential race samples without replacement with a capped dwell-time boost."""
    weight = 1 + min(max(seconds, 0) / HOT_SECONDS, 9)
    return -math.log1p(-random.random()) / weight


def diversity_score(totals: list[float]) -> float:
    """Simpson diversity: zero for one category, approaching 100 as listening spreads."""
    total = sum(totals)
    return 100 * (1 - sum((value / total) ** 2 for value in totals)) if total else 0


def duration(seconds: float) -> str:
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02}m" if hours else f"{minutes}m {seconds:02}s"
