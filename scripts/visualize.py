"""
BA2 Visualisierung: Sampling Strategy Results
==============================================
Liest die CSV aus experiment.py und erzeugt fertige Grafiken.

Voraussetzungen:
  pip install matplotlib pandas

Ausfuehren:
  python scripts/visualize.py                         # neueste CSV in scripts/results/
  python scripts/visualize.py scripts/results/results_YYYYMMDD_HHMMSS.csv
"""

import sys
import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

# ── Einstellungen ─────────────────────────────────────────────────────────────

COLORS = {
    "always_on":  "#2196F3",  # Blau
    "head_10":    "#FF9800",  # Orange
    "head_01":    "#F44336",  # Rot
    "tail_1500ms": "#9C27B0",  # Lila
    "adaptive":   "#4CAF50",  # Gruen
}

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    return df[df["error"].isna()] if "error" in df.columns else df


def bar_colors(df: pd.DataFrame) -> list:
    return [COLORS.get(n, "#999") for n in df["name"]]


def save(fig, name: str):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, name)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"  Gespeichert: {path}")
    plt.close(fig)


# ── Grafik 1: Detection Rate ──────────────────────────────────────────────────

def plot_detection_rate(df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(9, 5))

    bars = ax.bar(df["label"], df["detection_rate_pct"], color=bar_colors(df), width=0.55, zorder=3)

    for bar, val in zip(bars, df["detection_rate_pct"]):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.5,
            f"{val:.1f}%",
            ha="center", va="bottom", fontsize=10, fontweight="bold"
        )

    ax.set_ylim(0, 115)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_ylabel("Detection Rate")
    ax.set_xlabel("Sampling-Strategie")
    ax.set_title("Detection Rate pro Sampling-Strategie\n"
                 "(Anteil erkannter Latenz-Ausreißer ≥ 500ms)")
    ax.axhline(100, color="gray", linestyle="--", linewidth=0.8, label="100% Referenz")
    ax.legend(fontsize=9)
    ax.grid(axis="y", linestyle="--", alpha=0.4, zorder=0)
    ax.set_axisbelow(True)
    plt.xticks(rotation=15, ha="right")
    plt.tight_layout()
    save(fig, "plot_detection_rate.png")


# ── Grafik 2: Trace-Volumen ───────────────────────────────────────────────────

def plot_trace_volume(df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(9, 5))

    bars = ax.bar(df["label"], df["traces_in_jaeger"], color=bar_colors(df), width=0.55, zorder=3)

    for bar, val in zip(bars, df["traces_in_jaeger"]):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            str(int(val)),
            ha="center", va="bottom", fontsize=10, fontweight="bold"
        )

    ax.set_ylabel("Anzahl Traces in Jaeger")
    ax.set_xlabel("Sampling-Strategie")
    ax.set_title("Trace-Volumen pro Sampling-Strategie\n"
                 f"(bei {df['n_requests'].iloc[0]} gesendeten Requests)")
    ax.grid(axis="y", linestyle="--", alpha=0.4, zorder=0)
    ax.set_axisbelow(True)
    plt.xticks(rotation=15, ha="right")
    plt.tight_layout()
    save(fig, "plot_trace_volume.png")


# ── Grafik 3: Detection Rate vs. Trace-Volumen (Scatter) ─────────────────────

def plot_tradeoff(df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(8, 5))

    for _, row in df.iterrows():
        color = COLORS.get(row["name"], "#999")
        ax.scatter(row["traces_in_jaeger"], row["detection_rate_pct"],
                   color=color, s=120, zorder=3)
        ax.annotate(
            row["label"],
            (row["traces_in_jaeger"], row["detection_rate_pct"]),
            textcoords="offset points", xytext=(8, 4), fontsize=9
        )

    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_xlabel("Traces in Jaeger (Speichervolumen)")
    ax.set_ylabel("Detection Rate")
    ax.set_title("Trade-off: Detection Rate vs. Trace-Volumen\n"
                 "(oben links = ideal)")
    ax.grid(linestyle="--", alpha=0.4, zorder=0)
    ax.set_axisbelow(True)
    plt.tight_layout()
    save(fig, "plot_tradeoff.png")


# ── Grafik 4: Avg & P95 Response Time ────────────────────────────────────────

def plot_latency(df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(9, 5))

    x = range(len(df))
    width = 0.3

    ax.bar([i - width/2 for i in x], df["avg_response_ms"],
           width=width, label="Avg", color="#90CAF9", zorder=3)
    bars_p95 = ax.bar([i + width/2 for i in x], df["p95_response_ms"],
                      width=width, label="P95", color=bar_colors(df), zorder=3)

    for bar in bars_p95:
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 5,
            f"{bar.get_height():.0f}ms",
            ha="center", va="bottom", fontsize=8
        )

    ax.set_xticks(list(x))
    ax.set_xticklabels(df["label"], rotation=15, ha="right")
    ax.set_ylabel("Response Time (ms)")
    ax.set_xlabel("Sampling-Strategie")
    ax.set_title("Client-seitige Response Time pro Sampling-Strategie")
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.4, zorder=0)
    ax.set_axisbelow(True)
    plt.tight_layout()
    save(fig, "plot_latency.png")


# ── Grafik 5: otelcol Ressourcen (falls vorhanden) ───────────────────────────

def plot_resources(df: pd.DataFrame):
    if "otelcol_mem_mb" not in df.columns or df["otelcol_mem_mb"].isna().all():
        print("  Keine otelcol Ressourcen-Daten vorhanden — Grafik übersprungen.")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    ax1.bar(df["label"], df["otelcol_mem_mb"], color=bar_colors(df), width=0.55, zorder=3)
    ax1.set_ylabel("Memory (MB)")
    ax1.set_title("otelcol Memory-Verbrauch")
    ax1.grid(axis="y", linestyle="--", alpha=0.4, zorder=0)
    ax1.set_axisbelow(True)
    plt.setp(ax1.get_xticklabels(), rotation=15, ha="right")

    if "spans_exported_per_s" in df.columns and not df["spans_exported_per_s"].isna().all():
        ax2.bar(df["label"], df["spans_exported_per_s"], color=bar_colors(df), width=0.55, zorder=3)
        ax2.set_ylabel("Spans/s (exportiert)")
        ax2.set_title("otelcol exportierte Spans/s")
        ax2.grid(axis="y", linestyle="--", alpha=0.4, zorder=0)
        ax2.set_axisbelow(True)
        plt.setp(ax2.get_xticklabels(), rotation=15, ha="right")

    plt.suptitle("otelcol Ressourcenverbrauch pro Sampling-Strategie", fontweight="bold")
    plt.tight_layout()
    save(fig, "plot_resources.png")


# ── Zusammenfassungs-Tabelle ──────────────────────────────────────────────────

def print_summary(df: pd.DataFrame):
    print(f"\n{'=' * 65}")
    print(f"  ZUSAMMENFASSUNG")
    print(f"{'=' * 65}")
    print(f"{'Strategie':<22} {'Traces':<8} {'Ausreißer':<11} {'Detection':<12} {'P95 ms'}")
    print("-" * 65)
    for _, row in df.iterrows():
        print(
            f"{row['label']:<22} "
            f"{int(row['traces_in_jaeger']):<8} "
            f"{int(row['outliers_in_jaeger']):<11} "
            f"{row['detection_rate_pct']:>6.1f}%      "
            f"{row['p95_response_ms']:.0f}"
        )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        csvs = sorted([f for f in os.listdir(RESULTS_DIR) if f.startswith("results_") and f.endswith(".csv")])
        if not csvs:
            print("Keine CSV in scripts/results/ gefunden.")
            print("Usage: python scripts/visualize.py scripts/results/results_YYYYMMDD_HHMMSS.csv")
            sys.exit(1)
        csv_path = os.path.join(RESULTS_DIR, csvs[-1])
        print(f"Neueste CSV verwendet: {csvs[-1]}")
    else:
        csv_path = sys.argv[1]

    print(f"Lade {csv_path}...")
    df = load_csv(csv_path)

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
