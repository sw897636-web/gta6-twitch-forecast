"""Forecast GTA VI's launch-day Twitch viewers hour by hour (make.fun bounty
gta6-twitch-ccu-forecast-01).

Method (computed at run time from the case's own comparables; nothing about
the shape of past launches is hard-coded):

For every comparable past launch, take its release-day hourly viewers and
divide by that launch's hour-1 viewers, giving a log-ratio curve
log(viewers_h / viewers_1) for h = 2..24.  Hour 1 is 00:00-01:00 UTC, when
only New Zealand / Australia / Asia and the UK have unlocked, so hour 1 is a
noisy anchor: across past launches a big hour 1 means a *small* later
growth ratio (the evening peak in absolute viewers is far more stable
across launches than hour 1 is), and a small hour 1 means a large later
ratio.  So for each hour we regress the log ratio on the log of hour-1
viewers across comparables (ordinary least squares), shrink the slope by
0.7 towards zero to avoid over-trusting a 37-launch fit, and blend the
result 75/25 with the plain median log ratio as a hedge against the
regression extrapolating badly for a launch bigger than any comparable.
The target's log hour-1 is clamped to the comparables' observed range, so
beyond that range the forecast scales linearly with hour 1 instead of
following the regression line further out.

Spread: the per-hour sigma is the MAD (scaled by 1.4826) of the residuals
around the unshrunk regression line, floored at 0.30 and capped at 1.0 log
units, plus 0.10 when the target's hour 1 lies outside the comparables'
hour-1 range (an unprecedented launch deserves wider bands).  Quantiles are
then q_tau = p1 * exp(pred_h) * exp(z_tau * sigma_h) with the standard
normal quantiles z = (-1.645, -0.674, 0, 0.674, 1.645).

The Grand Theft Auto VI category's own pre-release history, shipped as a
comparable, is not a launch (its day is the premiere, not a release day),
so it is excluded.  History, streams and categories_hourly may be null in
practice cases; they are not used.  If comparables are missing or too few
for an hour, the forecast falls back to a persistence forecast with a
baseline-style widening spread.

Standard library only, deterministic, no network, no file access outside
the input/output directories.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

# Regression slope shrinkage (0 = median only, 1 = full OLS slope).
SHRINK = 0.7
# Weight of the plain median log ratio in the blended log-ratio prediction.
MEDIAN_BLEND = 0.25
# Spread bounds, in natural-log units.
SIGMA_FLOOR = 0.30
SIGMA_CAP = 1.0
# Extra spread when the target's hour 1 is outside the comparables' range.
SIGMA_OUT_OF_RANGE = 0.10
# Minimum comparables needed to fit a regression for an hour.
MIN_POINTS = 8


def parse_time(text):
    """Parse an ISO 8601 timestamp (trailing Z allowed) to an aware datetime."""
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def median(values):
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def round2(x):
    """Round to 2 decimals, half up; whole numbers come back as ints."""
    scaled = x * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100.0
    return int(value) if float(value).is_integer() else value


def comparable_ratios(case):
    """Per-hour (log hour-1, log ratio) points from the case's comparables.

    Returns (points, log_p1_range) where points maps hour -> list of
    (log_p1, log_ratio) and log_p1_range is (min, max) log hour-1 over the
    comparables used.  Non-launch entries (the target category's own
    pre-release history) are excluded.
    """
    points = {}
    log_p1s = []
    for comp in case.get("comparables") or []:
        if not isinstance(comp, dict):
            continue
        name = comp.get("name") or ""
        unlock = comp.get("unlock") or ""
        if "before release" in name or unlock.startswith("Not a launch"):
            continue
        day_start = parse_time(comp.get("day_start"))
        hourly = comp.get("hourly") or []
        if day_start is None or not hourly:
            continue
        by_hour = {}
        for row in hourly:
            if not isinstance(row, dict):
                continue
            viewers = row.get("viewers")
            if not isinstance(viewers, (int, float)) or viewers <= 0:
                continue
            at = parse_time(row.get("from"))
            if at is None:
                continue
            hour = int((at - day_start).total_seconds() // 3600) + 1
            if 1 <= hour <= 24:
                by_hour[hour] = float(viewers)
        p1 = by_hour.get(1)
        if p1 is None or p1 <= 0:
            continue
        log_p1 = math.log(p1)
        log_p1s.append(log_p1)
        for hour, viewers in by_hour.items():
            if hour == 1:
                continue
            points.setdefault(hour, []).append((log_p1, math.log(viewers / p1)))
    if not log_p1s:
        return points, None
    return points, (min(log_p1s), max(log_p1s))


def hour_forecast(log_p1, points_for_hour, log_range, hour):
    """Return (log-ratio prediction, sigma) for one hour."""
    pts = points_for_hour or []
    if len(pts) < MIN_POINTS:
        if pts:
            med = median([y for _, y in pts])
            spread = median([abs(y - med) for _, y in pts]) * 1.4826
            sigma = min(SIGMA_CAP, max(SIGMA_FLOOR, spread))
            return med, sigma
        # No usable comparables at all: persistence with a spread that
        # widens over the day, as the house baseline's does.
        sigma = min(SIGMA_CAP, max(SIGMA_FLOOR, 0.15 * math.sqrt(hour - 1)))
        return 0.0, sigma
    xs = [x for x, _ in pts]
    ys = [y for _, y in pts]
    n = len(pts)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    slope = 0.0
    if var_x > 0:
        slope = sum((x - mean_x) * (y - mean_y) for x, y in pts) / var_x
    clamped = log_p1
    out_of_range = False
    if log_range is not None:
        if clamped < log_range[0]:
            clamped = log_range[0]
            out_of_range = True
        elif clamped > log_range[1]:
            clamped = log_range[1]
            out_of_range = True
    pred_reg = mean_y + (slope * SHRINK) * (clamped - mean_x)
    pred_med = median(ys)
    pred = (1.0 - MEDIAN_BLEND) * pred_reg + MEDIAN_BLEND * pred_med
    residuals = [y - (mean_y + slope * (x - mean_x)) for x, y in pts]
    centre = median(residuals)
    sigma = 1.4826 * median([abs(r - centre) for r in residuals])
    if out_of_range:
        sigma += SIGMA_OUT_OF_RANGE
    sigma = min(SIGMA_CAP, max(SIGMA_FLOOR, sigma))
    return pred, sigma


def forecast_case(case, name):
    known = case.get("known") or []
    first = next((k for k in known if isinstance(k, dict) and k.get("hour") == 1), None)
    p1 = 1.0
    if first is not None:
        viewers = first.get("viewers")
        if isinstance(viewers, (int, float)) and viewers > 0:
            p1 = float(viewers)
    p1 = max(1.0, p1)
    log_p1 = math.log(p1)
    points, log_range = comparable_ratios(case)
    forecast_rows = case.get("forecast") or []
    wanted = []
    for row in forecast_rows:
        if not isinstance(row, dict):
            continue
        hour = row.get("hour")
        if isinstance(hour, int) and 2 <= hour <= 24 and hour not in wanted:
            wanted.append(hour)
    # Always emit all 23 hours, even if the case's forecast list is short.
    for hour in range(2, 25):
        if hour not in wanted:
            wanted.append(hour)
    hours = []
    for hour in sorted(wanted):
        pred, sigma = hour_forecast(log_p1, points.get(hour), log_range, hour)
        centre = p1 * math.exp(pred)
        quantiles = []
        previous = 0.0
        for z in Z:
            value = centre * math.exp(z * sigma)
            value = min(1e9, max(0.01, value))
            value = round2(value)
            if value < previous:
                value = previous
            quantiles.append(value)
            previous = value
        hours.append({"hour": hour, "q": quantiles})
    hours.sort(key=lambda r: r["hour"])
    return {"hours": hours}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        out_path = OUTPUT_DIR / (path.stem + ".out")
        out_path.write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
