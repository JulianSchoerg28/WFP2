"""
BA2 Visualisierung: Sampling Strategy Results
==============================================
Liest ALLE results_*.csv aus scripts/results/ und aggregiert sie automatisch.
Zeigt Mean-Werte mit Standardabweichungs-Fehlerbalken (Error Bars).

Voraussetzungen:
  pip install matplotlib pandas

Ausfuehren:
  python scripts/visualize.py              # alle CSVs aggregieren
  python scripts/visualize.py results/results_YYYYMMDD_HHMMSS.csv  # einzelner Lauf
"""

import glob
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import pandas as pd

# ── Einstellungen ─────────────────────────────────────────────────────────────

COLORS = {
    "always_on":   "#2196F3",   # Blau
    "head_10":     "#FF9800",   # Orange
    "head_01":     "#F44336",   # Rot
    "tail_1500ms": "#9C27B0",   # Lila
    "adaptive":    "#4CAF50",   # Gruen
}

STRATEGY_ORDER = ["always_on", "head_10", "head_01", "tail_1500ms", "adaptive"]

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

# ── Datenladen & Aggregation ──────────────────────────────────────────────────

METRIC_COLS = [
    "detection_rate_pct", "missed_critical_traces",
    "traces_in_jaeger", "outliers_in_jaeger",
    "avg_response_ms", "p95_response_ms", "p99_response_ms",
    "otelcol_cpu_rate", "otelcol_mem_mb",
    "spans_received_per_s", "spans_exported_per_s",
]


def _sort_by_strategy(df: pd.DataFrame) -> pd.DataFrame:
    order = {n: i for i, n in enumerate(STRATEGY_ORDER)}
    df = df.copy()
    df["_order"] = df["name"].map(order).fillna(99)
    return df.sort_values("_order").drop(columns="_order").reset_index(drop=True)


def load_all_csvs() -> pd.DataFrame:
    """Liest alle results_*.csv und gibt einen aggregierten DataFrame zurueck."""
    csvs = sorted(glob.glob(os.path.join(RESULTS_DIR, "results_*.csv")))
    if not csvs:
        return pd.DataFrame()

    dfs = []
    for f in csvs:
        df = pd.read_csv(f)
        if "error" in df.columns:
            df = df[df["error"].isna()]
        dfs.append(df)

    print(f"  {len(csvs)} CSV(s) gefunden und geladen.")
    all_data = pd.concat(dfs, ignore_index=True)

    available = [c for c in METRIC_COLS if c in all_data.columns]
    labels   = all_data.groupby("name")["label"].first()
    n_runs   = all_data.groupby("name").size().rename("n_runs")
    n_req    = all_data.groupby("name")["n_requests"].mean().rename("n_requests").round(0).astype(int)
    mean_df  = all_data.groupby("name")[available].mean()
    std_df   = all_data.groupby("name")[available].std(ddof=1).rename(
        columns={c: f"{c}_std" for c in available}
    )

    result = pd.concat([labels, n_runs, n_req, mean_df, std_df], axis=1).reset_index()
    return _sort_by_strategy(result)


def load_single_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "error" in df.columns:
        df = df[df["error"].isna()]
    df["n_runs"] = 1
    return _sort_by_strategy(df)


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def bar_colors(df: pd.DataFrame) -> list:
    return [COLORS.get(n, "#999") for n in df["name"]]


def get_yerr(df: pd.DataFrame, col: str):
    std_col = f"{col}_std"
    if std_col in df.columns and not df[std_col].isna().all():
        return df[std_col].fillna(0).values
    return None


def add_errorbars(ax, df: pd.DataFrame, col: str, x_positions):
    yerr = get_yerr(df, col)
    if yerr is not None:
        ax.errorbar(
            x_positions, df[col], yerr=yerr,
            fmt="none", color="black", capsize=5, linewidth=1.5, zorder=5,
        )


def run_info(df: pd.DataFrame) -> str:
    n = int(df["n_runs"].min()) if "n_runs" in df.columns else 1
    n_req = int(df["n_requests"].mean()) if "n_requests" in df.columns else "?"
    if n > 1:
        return f"n={n} Läufe · je ~{n_req} Requests"
    return f"{n_req} Requests"


def save(fig, name: str):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, name)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"  Gespeichert: {path}")
    plt.close(fig)


# ── Grafik 1: Detection Rate ──────────────────────────────────────────────────

def plot_detection_rate(df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(9, 5))
    x = list(range(len(df)))
    colors = bar_colors(df)

    ax.bar(x, df["detection_rate_pct"], color=colors, width=0.55, zorder=3)
    add_errorbars(ax, df, "detection_rate_pct", x)

    for i, (val, name) in enumerate(zip(df["detection_rate_pct"], df["name"])):
        yerr = get_yerr(df, "detection_rate_pct")
        offset = (yerr[i] if yerr is not None else 0) + 2
        ax.text(i, val + offset, f"{val:.1f}%",
                ha="center", va="bottom", fontsize=10, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(df["label"], rotation=15, ha="right")
    ax.set_ylim(0, 125)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_ylabel("Detection Rate (Mean)")
    ax.set_xlabel("Sampling-Strategie")
    ax.set_title(
        f"Detection Rate pro Sampling-Strategie\n"
        f"(Anteil erkannter Latenz-Ausreißer ≥ 1500ms · {run_info(df)})"
    )
    ax.axhline(100, color="gray", linestyle="--", linewidth=0.8, label="100 % Referenz")
    ax.legend(fontsize=9)
    ax.grid(axis="y", linestyle="--", alpha=0.4, zorder=0)
    ax.set_axisbelow(True)
    plt.tight_layout()
    save(fig, "plot_detection_rate.png")


# ── Grafik 2: Trace-Volumen ───────────────────────────────────────────────────

def plot_trace_volume(df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(9, 5))
    x = list(range(len(df)))
    colors = bar_colors(df)

    ax.bar(x, df["traces_in_jaeger"], color=colors, width=0.55, zorder=3)
    add_errorbars(ax, df, "traces_in_jaeger", x)

    for i, val in enumerate(df["traces_in_jaeger"]):
        yerr = get_yerr(df, "traces_in_jaeger")
        offset = (yerr[i] if yerr is not None else 0) + 0.5
        ax.text(i, val + offset, str(int(round(val))),
                ha="center", va="bottom", fontsize=10, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(df["label"], rotation=15, ha="right")
    ax.set_ylabel("Anzahl Traces in Jaeger (Mean)")
    ax.set_xlabel("Sampling-Strategie")
    n_req = int(df["n_requests"].mean()) if "n_requests" in df.columns else "?"
    ax.set_title(
        f"Trace-Volumen pro Sampling-Strategie\n"
        f"(bei ~{n_req} Requests/Lauf · {run_info(df)})"
    )
    ax.grid(axis="y", linestyle="--", alpha=0.4, zorder=0)
    ax.set_axisbelow(True)
    plt.tight_layout()
    save(fig, "plot_trace_volume.png")


# ── Grafik 3: Detection Rate vs. Trace-Volumen (Scatter) ─────────────────────

def plot_tradeoff(df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(8, 5))

    xerr = get_yerr(df, "traces_in_jaeger")
    yerr = get_yerr(df, "detection_rate_pct")

    for i, (_, row) in enumerate(df.iterrows()):
        color = COLORS.get(row["name"], "#999")
        xe = xerr[i] if xerr is not None else None
        ye = yerr[i] if yerr is not None else None
        ax.errorbar(
            row["traces_in_jaeger"], row["detection_rate_pct"],
            xerr=xe, yerr=ye,
            fmt="o", color=color, markersize=10,
            capsize=4, linewidth=1.5, zorder=3,
        )
        ax.annotate(
            row["label"],
            (row["traces_in_jaeger"], row["detection_rate_pct"]),
            textcoords="offset points", xytext=(8, 4), fontsize=9,
        )

    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_xlabel("Traces in Jaeger (Speichervolumen · Mean)")
    ax.set_ylabel("Detection Rate (Mean)")
    ax.set_title(
        f"Trade-off: Detection Rate vs. Trace-Volumen\n"
        f"(oben links = ideal · {run_info(df)})"
    )
    ax.grid(linestyle="--", alpha=0.4, zorder=0)
    ax.set_axisbelow(True)
    plt.tight_layout()
    save(fig, "plot_tradeoff.png")


# ── Grafik 4: Avg & P95 Response Time ────────────────────────────────────────

def plot_latency(df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(9, 5))
    x = list(range(len(df)))
    width = 0.3

    x_avg = [i - width / 2 for i in x]
    x_p95 = [i + width / 2 for i in x]

    ax.bar(x_avg, df["avg_response_ms"], width=width, label="Avg", color="#90CAF9", zorder=3)
    add_errorbars(ax, df, "avg_response_ms", x_avg)

    ax.bar(x_p95, df["p95_response_ms"], width=width, label="P95",
           color=bar_colors(df), zorder=3)
    add_errorbars(ax, df, "p95_response_ms", x_p95)

    for i, val in enumerate(df["p95_response_ms"]):
        ax.text(x_p95[i], val + 5, f"{val:.0f}ms",
                ha="center", va="bottom", fontsize=8)

    ax.set_xticks(x)
    ax.set_xticklabels(df["label"], rotation=15, ha="right")
    ax.set_ylabel("Response Time (ms · Mean)")
    ax.set_xlabel("Sampling-Strategie")
    ax.set_title(
        f"Client-seitige Response Time pro Sampling-Strategie\n({run_info(df)})"
    )
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.4, zorder=0)
    ax.set_axisbelow(True)
    plt.tight_layout()
    save(fig, "plot_latency.png")


# ── Grafik 5: otelcol Ressourcen ─────────────────────────────────────────────

def plot_resources(df: pd.DataFrame):
    has_mem   = "otelcol_mem_mb" in df.columns and not df["otelcol_mem_mb"].isna().all()
    has_spans = "spans_exported_per_s" in df.columns and not df["spans_exported_per_s"].isna().all()
    has_recv  = "spans_received_per_s" in df.columns and not df["spans_received_per_s"].isna().all()

    if not has_mem and not has_spans:
        print("  Keine otelcol Ressourcen-Daten vorhanden — Grafik uebersprungen.")
        return

    fig, axes = plt.subplots(1, 3 if (has_spans and has_recv) else 2, figsize=(14, 5))
    x = list(range(len(df)))
    colors = bar_colors(df)

    ax_idx = 0

    # Memory
    ax = axes[ax_idx]; ax_idx += 1
    ax.bar(x, df["otelcol_mem_mb"].fillna(0), color=colors, width=0.55, zorder=3)
    add_errorbars(ax, df, "otelcol_mem_mb", x)
    ax.set_xticks(x)
    ax.set_xticklabels(df["label"], rotation=15, ha="right")
    ax.set_ylabel("Memory (MB)")
    ax.set_title("otelcol Memory-Verbrauch")
    ax.grid(axis="y", linestyle="--", alpha=0.4, zorder=0)
    ax.set_axisbelow(True)

    # Spans received
    if has_recv:
        ax = axes[ax_idx]; ax_idx += 1
        ax.bar(x, df["spans_received_per_s"].fillna(0), color=colors, width=0.55, zorder=3)
        add_errorbars(ax, df, "spans_received_per_s", x)
        ax.set_xticks(x)
        ax.set_xticklabels(df["label"], rotation=15, ha="right")
        ax.set_ylabel("Spans/s")
        ax.set_title("otelcol empfangene Spans/s")
        ax.grid(axis="y", linestyle="--", alpha=0.4, zorder=0)
        ax.set_axisbelow(True)

    # Spans exported
    if has_spans:
        ax = axes[ax_idx]; ax_idx += 1
        ax.bar(x, df["spans_exported_per_s"].fillna(0), color=colors, width=0.55, zorder=3)
        add_errorbars(ax, df, "spans_exported_per_s", x)
        ax.set_xticks(x)
        ax.set_xticklabels(df["label"], rotation=15, ha="right")
        ax.set_ylabel("Spans/s")
        ax.set_title("otelcol exportierte Spans/s")
        ax.grid(axis="y", linestyle="--", alpha=0.4, zorder=0)
        ax.set_axisbelow(True)

    fig.suptitle(
        f"otelcol Ressourcenverbrauch pro Sampling-Strategie  ({run_info(df)})",
        fontweight="bold",
    )
    plt.tight_layout()
    save(fig, "plot_resources.png")


# ── Zusammenfassungs-Tabelle ──────────────────────────────────────────────────

def print_summary(df: pd.DataFrame):
    n_runs = int(df["n_runs"].min()) if "n_runs" in df.columns else 1
    has_std = any(f"{c}_std" in df.columns for c in METRIC_COLS)

    print(f"\n{'=' * 75}")
    if n_runs > 1:
        print(f"  ERGEBNISSE  (n={n_runs} Läufe · Mean ± Std)")
    else:
        print(f"  ERGEBNISSE  (1 Lauf)")
    print(f"{'=' * 75}")

    hdr_std = "  ±Std" if has_std else ""
    print(f"{'Strategie':<22} {'Traces':<10} {'Ausreißer':<11} {'Detection':<18} {'P95 ms':<14}{hdr_std}")
    print("-" * 75)

    for _, row in df.iterrows():
        traces  = int(round(row["traces_in_jaeger"]))
        outlier = int(round(row["outliers_in_jaeger"]))
        det     = row["detection_rate_pct"]
        p95     = row["p95_response_ms"]

        if has_std:
            det_std = row.get("detection_rate_pct_std", float("nan"))
            p95_std = row.get("p95_response_ms_std", float("nan"))
            print(
                f"{row['label']:<22} "
                f"{traces:<10} "
                f"{outlier:<11} "
                f"{det:>6.1f}% ±{det_std:4.1f}%   "
                f"{p95:>6.0f}ms ±{p95_std:.0f}ms"
            )
        else:
            print(
                f"{row['label']:<22} "
                f"{traces:<10} "
                f"{outlier:<11} "
                f"{det:>6.1f}%            "
                f"{p95:>6.0f}ms"
            )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) >= 2:
        csv_path = sys.argv[1]
        print(f"Einzelner Lauf: {csv_path}")
        df = load_single_csv(csv_path)
    else:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        df = load_all_csvs()
        if df.empty:
            print("Keine CSV in scripts/results/ gefunden.")
            print("Usage: python scripts/visualize.py scripts/results/results_YYYYMMDD_HHMMSS.csv")
            sys.exit(1)

    print("Erzeuge Grafiken...")
    plot_detection_rate(df)
    plot_trace_volume(df)
    plot_tradeoff(df)
    plot_latency(df)
    plot_resources(df)

    print_summary(df)
    print(f"\nAlle Grafiken gespeichert in: {RESULTS_DIR}")


if __name__ == "__main__":
    main()
