"""
BA2 Aggregation
===============
Liest alle results_*.csv aus scripts/results/, berechnet fuer jede Strategie
Mean, Standardabweichung, Min, Max und 95%-Konfidenzintervall.
Fuehrt Welch-t-Tests gegen Always-On (Baseline) durch.
Speichert das Ergebnis als aggregated_TIMESTAMP.csv.

Voraussetzungen:
  pip install pandas scipy

Ausfuehren:
  python scripts/aggregate.py
"""

import glob
import math
import os
import sys
from datetime import datetime

import pandas as pd

try:
    from scipy import stats as _scipy_stats
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

METRICS = [
    ("detection_rate_pct",    "Detection Rate",          "%",   1),
    ("missed_critical_traces","Verlorene Traces",        "",    1),
    ("traces_in_jaeger",      "Traces in Jaeger",        "",    0),
    ("outliers_in_jaeger",    "Ausreisser in Jaeger",    "",    0),
    ("avg_response_ms",       "Avg Response",            "ms",  1),
    ("p95_response_ms",       "P95 Response",            "ms",  1),
    ("p99_response_ms",       "P99 Response",            "ms",  1),
    ("otelcol_cpu_rate",      "otelcol CPU Rate",        "",    4),
    ("otelcol_mem_mb",        "otelcol Memory",          "MB",  0),
    ("spans_received_per_s",  "Spans received/s",        "",    1),
    ("spans_exported_per_s",  "Spans exported/s",        "",    1),
]

STRATEGY_ORDER = ["always_on", "head_10", "head_01", "tail_1500ms", "adaptive"]
BASELINE       = "always_on"

# Metriken fuer die t-Tests berechnet werden
TTEST_METRICS = ["detection_rate_pct", "missed_critical_traces", "traces_in_jaeger",
                 "otelcol_mem_mb", "spans_exported_per_s"]


def load_all(results_dir: str):
    csvs = sorted(glob.glob(os.path.join(results_dir, "results_*.csv")))
    if not csvs:
        print("Keine results_*.csv in scripts/results/ gefunden.")
        sys.exit(1)

    dfs = []
    for f in csvs:
        df = pd.read_csv(f)
        if "error" in df.columns:
            df = df[df["error"].isna()]
        dfs.append(df)

    print(f"  {len(csvs)} CSV(s) geladen")
    return pd.concat(dfs, ignore_index=True), len(csvs)


def ci95(series: pd.Series) -> float:
    n = series.count()
    if n < 2:
        return float("nan")
    return 1.96 * series.std(ddof=1) / math.sqrt(n)


def aggregate(all_data: pd.DataFrame) -> pd.DataFrame:
    cols = [m for m, *_ in METRICS if m in all_data.columns]

    labels  = all_data.groupby("name")["label"].first()
    n_runs  = all_data.groupby("name").size().rename("n_runs")
    n_req   = all_data.groupby("name")["n_requests"].mean().rename("n_requests_mean").round(0).astype(int)
    mean_df = all_data.groupby("name")[cols].mean().rename(columns={c: f"{c}_mean" for c in cols})
    std_df  = all_data.groupby("name")[cols].std(ddof=1).rename(columns={c: f"{c}_std"  for c in cols})
    min_df  = all_data.groupby("name")[cols].min().rename(columns={c: f"{c}_min"  for c in cols})
    max_df  = all_data.groupby("name")[cols].max().rename(columns={c: f"{c}_max"  for c in cols})
    ci_df   = all_data.groupby("name")[cols].apply(
        lambda g: g.apply(ci95)
    ).rename(columns={c: f"{c}_ci95" for c in cols})

    result = pd.concat([labels, n_runs, n_req, mean_df, std_df, min_df, max_df, ci_df], axis=1).reset_index()

    order_map = {n: i for i, n in enumerate(STRATEGY_ORDER)}
    result["_order"] = result["name"].map(order_map).fillna(99)
    result = result.sort_values("_order").drop(columns="_order").reset_index(drop=True)
    return result


def run_ttests(all_data: pd.DataFrame) -> dict:
    """
    Welch-t-Test (ungleiche Varianzen) fuer jede Nicht-Baseline-Strategie vs. Always-On.
    Gibt dict { strategie_name: { metrik: (t, p, sig) } } zurueck.
    """
    if not HAS_SCIPY:
        return {}

    baseline_data = all_data[all_data["name"] == BASELINE]
    results = {}

    for name in all_data["name"].unique():
        if name == BASELINE:
            continue
        group_data = all_data[all_data["name"] == name]
        metric_results = {}

        for col in TTEST_METRICS:
            if col not in all_data.columns:
                continue
            a = baseline_data[col].dropna().values
            b = group_data[col].dropna().values
            if len(a) < 2 or len(b) < 2:
                metric_results[col] = (float("nan"), float("nan"), "n.a. (zu wenig Daten)")
                continue
            t, p = _scipy_stats.ttest_ind(a, b, equal_var=False)
            if p < 0.001:
                sig = "*** (p<0.001)"
            elif p < 0.01:
                sig = "**  (p<0.01)"
            elif p < 0.05:
                sig = "*   (p<0.05)"
            else:
                sig = "n.s. (p≥0.05)"
            metric_results[col] = (round(t, 3), round(p, 4), sig)

        results[name] = metric_results

    return results


def print_table(agg: pd.DataFrame):
    print(f"\n{'=' * 70}")
    print("  AGGREGIERTE ERGEBNISSE")
    print(f"{'=' * 70}")

    for _, row in agg.iterrows():
        n     = int(row["n_runs"])
        label = row["label"]
        n_req = int(row.get("n_requests_mean", 0))
        print(f"\n  {label}  (n={n} Laeufe, je ~{n_req} Requests)")
        print(f"  {'─' * 50}")

        for col, name, unit, decimals in METRICS:
            mean_col = f"{col}_mean"
            std_col  = f"{col}_std"
            ci_col   = f"{col}_ci95"
            if mean_col not in row.index or pd.isna(row[mean_col]):
                continue
            mean_val = row[mean_col]
            std_val  = row.get(std_col, float("nan"))
            ci_val   = row.get(ci_col, float("nan"))
            fmt      = f".{decimals}f"
            unit_str = f" {unit}" if unit else ""
            print(
                f"    {name:<26} {mean_val:{fmt}}{unit_str}"
                f"  ±{std_val:{fmt}}"
                f"  95%-CI ±{ci_val:{fmt}}"
            )


def print_ttests(ttest_results: dict, all_data: pd.DataFrame):
    if not ttest_results:
        if not HAS_SCIPY:
            print("\n  T-Tests: scipy nicht installiert — pip install scipy")
        return

    labels = all_data.groupby("name")["label"].first().to_dict()

    print(f"\n{'=' * 70}")
    print(f"  WELCH T-TESTS vs. Baseline (Always-On 100%)")
    print(f"  H0: kein Unterschied zur Baseline  |  α = 0.05")
    print(f"{'=' * 70}")

    metric_labels = {c: n for c, n, *_ in METRICS}

    for name, metric_results in ttest_results.items():
        label = labels.get(name, name)
        print(f"\n  {label}")
        print(f"  {'─' * 50}")
        for col, (t, p, sig) in metric_results.items():
            mname = metric_labels.get(col, col)
            print(f"    {mname:<26}  t={t:>7.3f}  p={p:.4f}  {sig}")


def save_csv(agg: pd.DataFrame, results_dir: str) -> str:
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(results_dir, f"aggregated_{ts}.csv")
    agg.to_csv(path, index=False, float_format="%.4f")
    return path


def main():
    print("=" * 55)
    print("  BA2 Aggregation")
    print("=" * 55)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    all_data, _ = load_all(RESULTS_DIR)
    agg          = aggregate(all_data)

    print_table(agg)
    print_ttests(run_ttests(all_data), all_data)

    path = save_csv(agg, RESULTS_DIR)
    print(f"\n  Aggregierte CSV: {path}")
    print(f"  Grafiken:        python scripts/visualize.py")


if __name__ == "__main__":
    main()
