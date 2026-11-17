# Forecast GTA VI's launch-day Twitch viewers hour by hour

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/sw897636-web/gta6-twitch-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/sw897636-web/gta6-twitch-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Entry for make.fun's ["Forecast GTA VI's launch-day Twitch viewers hour by hour"](https://make.fun/bounty/gta6-twitch-ccu-forecast-01) bounty ($250 in USDC).

`main.py` (Python 3.13, standard library only) reads one case file
`/input/<id>.in` — everything recorded up to the end of the release day's
first hour, that hour's viewer count included — and writes
`/output/<id>.out`: for each of hours 2–24, five quantiles (5%, 25%, 50%,
75%, 95%) of that hour's concurrent Twitch viewers in the Grand Theft Auto
VI category.

## How it forecasts

Nothing about the shape of past launches is hard-coded; the curve and the
spread are computed at run time from the case's own `comparables` (38 past
big launches' release-day hourly curves in a practice case, 42 in the
final).

- For each comparable launch, divide its release-day hourly viewers by its
  hour-1 viewers to get a log-ratio curve.
- Hour 1 is 00:00–01:00 UTC, when only New Zealand / Australia / Asia and
  the UK have unlocked, so it is a noisy anchor: across past launches a big
  hour 1 means a *small* later growth ratio (the evening peak in absolute
  viewers is far more stable across launches than hour 1 is). For each hour
  the log ratio is therefore regressed on the log of hour-1 viewers across
  comparables (OLS), the slope shrunk by 0.7, and the result blended 75/25
  with the plain median log ratio as a hedge against extrapolating beyond
  any comparable launch. The target's log hour-1 is clamped to the
  comparables' observed range.
- Spread: the per-hour sigma is the scaled MAD of the residuals around the
  unshrunk regression line, floored at 0.30 and capped at 1.0 log units,
  plus 0.10 when the target's hour 1 lies outside the comparables' range.
  Quantiles are `q = p1 * exp(pred) * exp(z * sigma)`.
- The GTA VI category's own pre-release history (shipped as a comparable)
  is excluded — it is not a launch. Missing/null `history`, `streams` and
  `categories_hourly` are tolerated, and missing comparables fall back to a
  persistence forecast with a widening spread.

The program is deterministic (two runs write byte-identical output), runs
in ~0.1 s per case, uses no network, and reads nothing outside the input
directory.

## Practice results

Scored locally against the four practice launches' real SullyGnome hourly
averages (answers fetched from SullyGnome's public API and checked against
each case's hour-1 print):

| | pinball loss | typical miss | 90% coverage |
|---|---|---|---|
| This entry | **0.211** | 27.7% | 0.967 |
| House baseline (starter) | 0.387 | 82.7% | 0.783 |

Per case: p00 0.217, p01 0.202, p02 0.176, p03 0.250 (baseline: 0.744,
0.287, 0.215, 0.303). Practice scores are no guide to the final — the
final is one unseen day — but the entry beats the baseline on every
practice case.

## Run locally

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

## License

MIT — see [LICENSE](LICENSE).
