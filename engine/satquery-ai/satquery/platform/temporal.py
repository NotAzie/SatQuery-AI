"""Reusable timezone-aware temporal utilities for observation records."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Optional, TypeVar

from .contracts import Observation, TemporalExtent

T = TypeVar("T")


def as_utc(value: datetime) -> datetime:
    """Return an aware datetime normalized to UTC."""
    if value.tzinfo is None:
        raise ValueError("datetime must include a timezone")
    return value.astimezone(timezone.utc)


def overlaps(
    first: TemporalExtent, second: TemporalExtent, *, inclusive: bool = True
) -> bool:
    """Return whether two open or closed intervals overlap."""
    if first.end is not None and second.start is not None:
        if first.end < second.start or (
            not inclusive and first.end == second.start
        ):
            return False
    if second.end is not None and first.start is not None:
        if second.end < first.start or (
            not inclusive and second.end == first.start
        ):
            return False
    return True


def rolling_windows(
    start: datetime,
    end: datetime,
    *,
    width: timedelta,
    step: Optional[timedelta] = None,
) -> tuple[TemporalExtent, ...]:
    """Split a temporal interval into deterministic, half-open windows."""
    start_utc = as_utc(start)
    end_utc = as_utc(end)
    stride = step or width
    if width <= timedelta(0) or stride <= timedelta(0):
        raise ValueError("window width and step must be positive")
    if start_utc > end_utc:
        raise ValueError("window start must not be after end")
    if start_utc == end_utc:
        return (TemporalExtent(start=start_utc, end=end_utc),)
    windows: list[TemporalExtent] = []
    cursor = start_utc
    while cursor < end_utc:
        window_end = min(cursor + width, end_utc)
        windows.append(TemporalExtent(start=cursor, end=window_end))
        cursor += stride
    return tuple(windows)


def seasonal_windows(
    start: datetime,
    end: datetime,
    *,
    start_month: int,
    duration_months: int = 3,
) -> tuple[TemporalExtent, ...]:
    """Return recurring calendar-season windows intersecting a UTC range."""
    start_utc = as_utc(start)
    end_utc = as_utc(end)
    if start_utc > end_utc:
        raise ValueError("window start must not be after end")
    if not 1 <= start_month <= 12:
        raise ValueError("start_month must be between 1 and 12")
    if duration_months < 1 or duration_months > 12:
        raise ValueError("duration_months must be between 1 and 12")
    result: list[TemporalExtent] = []
    for year in range(start_utc.year - 1, end_utc.year + 1):
        season_start = datetime(year, start_month, 1, tzinfo=timezone.utc)
        season_end = _add_months(season_start, duration_months)
        if season_end <= start_utc or season_start >= end_utc:
            continue
        result.append(
            TemporalExtent(
                start=max(season_start, start_utc),
                end=min(season_end, end_utc),
            )
        )
    return tuple(result)


def group_by_temporal_windows(
    observations: Iterable[Observation],
    windows: Iterable[TemporalExtent],
) -> tuple[tuple[TemporalExtent, tuple[Observation, ...]], ...]:
    """Assign each observation to every matching temporal window."""
    ordered_observations = chronological(observations)
    ordered_windows = tuple(
        sorted(
            windows,
            key=lambda item: (
                item.start is None,
                item.start or datetime.max.replace(tzinfo=timezone.utc),
                item.end is None,
                item.end or datetime.max.replace(tzinfo=timezone.utc),
            ),
        )
    )
    groups: list[tuple[TemporalExtent, tuple[Observation, ...]]] = []
    for window in ordered_windows:
        selected = tuple(
            observation
            for observation in ordered_observations
            if observation.temporal_extent is not None
            and overlaps(observation.temporal_extent, window)
        )
        groups.append((window, selected))
    return tuple(groups)


def observation_timeline(
    observations: Iterable[Observation],
) -> tuple[Observation, ...]:
    """Return a deterministic history/future timeline, retaining untimed items last."""
    return chronological(observations)


def group_temporal_events(
    observations: Iterable[Observation],
    *,
    maximum_gap: timedelta = timedelta(0),
) -> tuple[tuple[Observation, ...], ...]:
    """Group observations whose temporal extents overlap or are within a gap."""
    if maximum_gap < timedelta(0):
        raise ValueError("maximum_gap must not be negative")
    ordered = chronological(
        (
            item
            for item in observations
            if item.temporal_extent is not None
            and item.temporal_extent.start is not None
            and item.temporal_extent.end is not None
        ),
        timestamp=lambda item: item.temporal_extent.start
        if item.temporal_extent is not None
        else None,
    )
    groups: list[list[Observation]] = []
    group_end: Optional[datetime] = None
    for observation in ordered:
        extent = observation.temporal_extent
        if extent is None or extent.start is None or extent.end is None:
            continue
        start = as_utc(extent.start)
        end = as_utc(extent.end)
        if not groups or group_end is None or start > group_end + maximum_gap:
            groups.append([observation])
            group_end = end
        else:
            groups[-1].append(observation)
            group_end = max(group_end, end)
    return tuple(tuple(group) for group in groups)


def historical_window(
    *, duration: timedelta, now: Optional[datetime] = None
) -> TemporalExtent:
    """Build a timezone-aware historical range ending at the supplied instant."""
    if duration <= timedelta(0):
        raise ValueError("duration must be positive")
    end = as_utc(now or datetime.now(timezone.utc))
    return TemporalExtent(start=end - duration, end=end)


def forecast_window(
    *, duration: timedelta, now: Optional[datetime] = None
) -> TemporalExtent:
    """Build a timezone-aware future range starting at the supplied instant."""
    if duration <= timedelta(0):
        raise ValueError("duration must be positive")
    start = as_utc(now or datetime.now(timezone.utc))
    return TemporalExtent(start=start, end=start + duration)


def chronological(
    observations: Iterable[T],
    *,
    timestamp: Optional[Callable[[T], Optional[datetime]]] = None,
) -> tuple[T, ...]:
    """Sort values by observation instant, then ID when available."""
    extract = timestamp or (
        lambda item: (
            getattr(item, "observed_at", None)
            or getattr(getattr(item, "temporal_extent", None), "start", None)
        )
    )

    def key(item: T) -> tuple[bool, datetime, str]:
        value = extract(item)
        identity = str(getattr(item, "observation_id", ""))
        if value is None:
            return True, datetime.max.replace(tzinfo=timezone.utc), identity
        return False, as_utc(value), identity

    return tuple(sorted(observations, key=key))


def freshness_seconds(
    observation: Observation, *, now: Optional[datetime] = None
) -> Optional[float]:
    """Return age from the source observation time; unknown time stays unknown."""
    instant = observation.observed_at
    if instant is None and observation.temporal_extent is not None:
        instant = observation.temporal_extent.end
    if instant is None:
        return None
    reference = as_utc(now or datetime.now(timezone.utc))
    return (reference - as_utc(instant)).total_seconds()


def _add_months(value: datetime, amount: int) -> datetime:
    month_index = value.year * 12 + value.month - 1 + amount
    year, month_zero = divmod(month_index, 12)
    return value.replace(year=year, month=month_zero + 1)
