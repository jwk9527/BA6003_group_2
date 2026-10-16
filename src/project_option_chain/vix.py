"""30-day volatility index (CBOE VIX / CSI iVIX methodology) from option prices.

Per expiry (T = calendar days / 365):
  1. For each strike take call and put prices (mid of bid/ask when both > 0,
     else last/settle).
  2. Forward F = K* + e^{RT} (C - P), K* = strike with the smallest |C - P|.
  3. K0 = largest strike <= F.
  4. Q(K): put if K < K0, call if K > K0, average of call and put at K0.
     Strikes with a non-positive price are dropped.
  5. ΔK_i = (K_{i+1} - K_{i-1}) / 2 (one-sided at the ends).
  6. σ² = (2/T) Σ ΔK/K² e^{RT} Q(K) - (1/T) (F/K0 - 1)².
Then 30-day interpolation in total variance:
  VIX = 100 √{ [T1σ1² (N2-N30)/(N2-N1) + T2σ2² (N30-N1)/(N2-N1)] × N365/N30 }
(weights fall outside [0,1] -> extrapolation when both expiries are on the
same side of 30 days). With one expiry only, VIX ≈ 100 σ1 (no term interpolation).

Roll (``roll_days``): 0 (default) always uses the two nearest expiries. With
``roll_days=7`` a near expiry with fewer than 7 calendar days left is skipped
(next and following expiry are used) when a third expiry is available.
Live always uses roll_days=0 (only front + next codes are archived).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .rates import get_shibor_rate


@dataclass(frozen=True)
class ExpiryVariance:
    expiry: str
    days: int
    T: float
    rate: float
    forward: float
    k0: float
    n_strikes: int
    variance: float          # σ² (annualised)

    @property
    def sigma(self) -> float:
        return float(np.sqrt(max(self.variance, 0.0)))


@dataclass(frozen=True)
class VixResult:
    near: ExpiryVariance | None
    next: ExpiryVariance | None
    vix: float | None        # in vol points (e.g. 45.3)
    method: str              # "interpolated" | "extrapolated" | "single-month" | "unavailable"
    note: str


def option_price_column(df: pd.DataFrame) -> pd.Series:
    """Best available option price per row: mid(bid, ask) > last > settle."""
    price = pd.Series(np.nan, index=df.index, dtype=float)
    if {"bid", "ask"}.issubset(df.columns):
        bid, ask = pd.to_numeric(df["bid"], errors="coerce"), pd.to_numeric(df["ask"], errors="coerce")
        ok = (bid > 0) & (ask > 0) & (ask >= bid)
        price = price.where(~ok, (bid + ask) / 2)
    for col in ("last", "settle"):
        if col in df.columns:
            price = price.fillna(pd.to_numeric(df[col], errors="coerce").where(lambda s: s > 0))
    return price


def expiry_variance(chain: pd.DataFrame, rate: float, expiry: str, days: int) -> ExpiryVariance | None:
    """σ² for one expiry. ``chain`` needs is_call, strike_price and a price column."""
    if days <= 0:
        return None
    T = days / 365.0
    df = chain.assign(price=option_price_column(chain))
    calls = df[df["is_call"] == 1].groupby("strike_price")["price"].mean()
    puts = df[df["is_call"] == 0].groupby("strike_price")["price"].mean()
    both = pd.concat([calls.rename("C"), puts.rename("P")], axis=1).dropna().sort_index()
    if len(both) < 3:
        return None
    growth = np.exp(rate * T)
    k_star = float((both["C"] - both["P"]).abs().idxmin())
    forward = k_star + growth * float(both.loc[k_star, "C"] - both.loc[k_star, "P"])
    strikes_all = np.sort(np.union1d(calls.index, puts.index))
    below = strikes_all[strikes_all <= forward]
    k0 = float(below.max()) if len(below) else float(strikes_all.min())

    q: dict[float, float] = {}
    for k in strikes_all:
        c, p = calls.get(k, np.nan), puts.get(k, np.nan)
        if k < k0:
            v = p
        elif k > k0:
            v = c
        else:
            v = np.nanmean([c, p]) if not (np.isnan(c) and np.isnan(p)) else np.nan
        if np.isfinite(v) and v > 0:
            q[float(k)] = float(v)
    ks = np.array(sorted(q))
    if len(ks) < 3:
        return None
    qv = np.array([q[k] for k in ks])
    dk = np.empty_like(ks)
    dk[0], dk[-1] = ks[1] - ks[0], ks[-1] - ks[-2]
    dk[1:-1] = (ks[2:] - ks[:-2]) / 2
    var = (2 / T) * np.sum(dk / ks**2 * growth * qv) - (1 / T) * (forward / k0 - 1) ** 2
    return ExpiryVariance(expiry, int(days), T, rate, float(forward), k0, len(ks), float(var))


def compute_vix(chain: pd.DataFrame, shibor_path: Path, target_days: int = 30, roll_days: int = 0) -> VixResult:
    """VIX from a (possibly multi-expiry) prepared chain (needs is_call, strike_price, DTE_n, date).

    Prices: mid(bid, ask) > last > settle per row (History passes settle only).
    """
    if chain is None or chain.empty:
        return VixResult(None, None, None, "unavailable", "No option data.")
    df = chain.copy()
    key = "expiry" if "expiry" in df.columns and df["expiry"].notna().all() else "DTE_n"
    valuation = pd.Timestamp(df["date"].iloc[0]).date()
    variances: list[ExpiryVariance] = []
    for exp, grp in df.groupby(key):
        days = int(grp["DTE_n"].iloc[0])
        if days <= 0:
            continue
        rate = get_shibor_rate(shibor_path, valuation, days)
        ev = expiry_variance(grp, rate, str(grp["expiry"].iloc[0]) if "expiry" in grp else f"{days}d", days)
        if ev is not None and ev.variance > 0:
            variances.append(ev)
    variances.sort(key=lambda e: e.days)
    if not variances:
        return VixResult(None, None, None, "unavailable",
                         "No expiry had enough priced strikes (need option prices for ≥3 strikes).")
    rolled = ""
    if roll_days > 0 and len(variances) >= 3 and variances[0].days < roll_days:
        rolled = f" Near expiry ({variances[0].days}d < {roll_days}d) rolled."
        variances = variances[1:]
    near = variances[0]
    if len(variances) == 1:
        return VixResult(near, None, round(100 * near.sigma, 2), "single-month",
                         f"Single expiry only ({near.days}d): VIX ≈ 100·σ_near, no 30-day term interpolation.")
    nxt = variances[1]
    n1, n2, n30 = near.days, nxt.days, target_days
    w1 = (n2 - n30) / (n2 - n1)
    total = near.T * near.variance * w1 + nxt.T * nxt.variance * (1 - w1)
    total_30 = total * 365 / n30
    method = "interpolated" if n1 <= n30 <= n2 else "extrapolated"
    note = (f"Linear interpolation in total variance between {n1}d and {n2}d to {n30}d."
            if method == "interpolated" else
            f"Both expiries are on the same side of {n30}d ({n1}d, {n2}d): linear extrapolation in total variance.")
    if total_30 <= 0:
        return VixResult(near, nxt, None, method, note + " Extrapolated variance ≤ 0 → undefined.")
    return VixResult(near, nxt, round(100 * float(np.sqrt(total_30)), 2), method, note + rolled)
