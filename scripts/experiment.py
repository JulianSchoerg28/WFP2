"""
BA2 Experiment Script: Sampling Strategy Evaluation
====================================================
Misst Detection Rate, Trace-Volumen und Ressourcenverbrauch
fuer jede Sampling-Strategie.

Voraussetzungen:
  - Docker Desktop laeuft
  - pip install requests
  - Admin-User existiert (wird automatisch angelegt)

Ausfuehren:
  python scripts/experiment.py
"""

import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime

import requests

# ── Konfiguration ─────────────────────────────────────────────────────────────

GW          = "http://localhost:8000"
JAEGER      = "http://localhost:16686"
PROMETHEUS  = "http://localhost:9090"

N_REQUESTS            = 100    # Requests pro Strategie
SPORADIC_EVERY_N      = 10     # Jeder N-te Request bekommt einen Spike → exakt N_REQUESTS/EVERY_N Ausreißer
SPORADIC_FIXED_MS     = 2000   # Feste Spike-Dauer in ms — weit über normaler System-Latenz
OUTLIER_THRESHOLD_MS  = 1500   # Schwellwert: klar über System-Latenz (~<300ms), klar unter Spike (2000ms)

# Welche Services bei Strategie-Wechsel neu gestartet werden
RESTARTABLE = [
    "otelcol", "api-gateway", "product-service", "auth-service",
    "order-service", "cart-service", "payment-service",
    "order-consumer", "log-service",
]

# Strategien die verglichen werden
STRATEGIES = [
    {
        "name":               "always_on",
        "label":              "Always-On (100%)",
        "SAMPLING_STRATEGY":  "always_on",
        "OTELCOL_CONFIG":     "passthrough",
    },
    {
        "name":               "head_10",
        "label":              "Head-based (10%)",
        "SAMPLING_STRATEGY":  "head",
        "SAMPLING_HEAD_RATE": "0.1",
        "OTELCOL_CONFIG":     "passthrough",
    },
    {
        "name":               "head_01",
        "label":              "Head-based (1%)",
        "SAMPLING_STRATEGY":  "head",
        "SAMPLING_HEAD_RATE": "0.01",
        "OTELCOL_CONFIG":     "passthrough",
    },
    {
        "name":                    f"tail_{OUTLIER_THRESHOLD_MS}ms",
        "label":                   f"Tail-based (>{OUTLIER_THRESHOLD_MS}ms)",
        "SAMPLING_STRATEGY":       "tail",
        "OTELCOL_CONFIG":          "tail",
        "TAIL_LATENCY_THRESHOLD_MS": str(OUTLIER_THRESHOLD_MS),
    },
]

# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def log(msg: str):
    print(f"  {msg}")


def update_env(overrides: dict):
    """Schreibt Werte in die .env Datei."""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    env_path = os.path.normpath(env_path)

    lines = []
    updated = set()

    with open(env_path, "r") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0]
                if key in overrides:
                    lines.append(f"{key}={overrides[key]}\n")
                    updated.add(key)
                    continue
            lines.append(line)

    for key, val in overrides.items():
        if key not in updated:
            lines.append(f"{key}={val}\n")

    with open(env_path, "w") as f:
        f.writelines(lines)


def docker(args: list, silent: bool = True):
    """Fuehrt einen docker compose Befehl aus."""
    cmd = ["docker", "compose"] + args
    if silent:
        subprocess.run(cmd, capture_output=True)
    else:
        subprocess.run(cmd)


def clear_jaeger():
    """Startet Jaeger neu um alle Traces zu loeschen."""
    log("Jaeger leeren...")
    docker(["restart", "jaeger"])
    time.sleep(4)


BUILDABLE = [
    "api-gateway", "product-service", "auth-service",
    "order-service", "cart-service", "payment-service",
    "order-consumer", "log-service",
]

def build_services():
    """Baut alle Service-Images neu (einmalig vor dem Experiment)."""
    log("Images bauen (einmalig, dauert ~1 Minute)...")
    docker(["build"] + BUILDABLE, silent=False)

def restart_services():
    """Startet alle relevanten Services neu (ohne DB/RabbitMQ)."""
    log("Services neu starten...")
    docker(["up", "-d", "--force-recreate"] + RESTARTABLE)


def wait_for_gateway(timeout: int = 150) -> bool:
    """Wartet bis der Gateway erreichbar ist."""
    log("Warte auf Gateway...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{GW}/health", timeout=2)
            if r.status_code == 200:
                log("Gateway bereit.")
                return True
        except Exception:
            pass
        time.sleep(2)
    log("TIMEOUT: Gateway nicht erreichbar!")
    return False


def ensure_admin():
    """Legt Admin-User an falls nicht vorhanden."""
    try:
        requests.post(
            f"{GW}/auth/register",
            json={"username": "admin", "password": "Admin123!"},
            timeout=5,
        )
    except Exception:
        pass
    try:
        requests.post(
            f"{GW}/auth/internal/create_admin",
            json={"username": "admin", "password": "Admin123!"},
            headers={"x-internal-key": "some-internal-key"},
            timeout=5,
        )
    except Exception:
        pass


def get_token() -> str:
    r = requests.post(
        f"{GW}/token",
        data={"username": "admin", "password": "Admin123!"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=5,
    )
    return r.json()["access_token"]


def send_requests(n: int) -> list[float]:
    """Schickt N GET /products/ Requests und gibt Response-Zeiten in ms zurueck.
    Jeder SPORADIC_EVERY_N-te Request bekommt X-Inject-Latency: true gesetzt."""
    times = []
    token = get_token()

    for i in range(n):
        if i > 0 and i % 20 == 0:
            try:
                token = get_token()
            except Exception:
                pass

        headers = {"Authorization": f"Bearer {token}"}
        if (i + 1) % SPORADIC_EVERY_N == 0:
            headers["X-Inject-Latency"] = "true"

        start = time.monotonic()
        try:
            requests.get(f"{GW}/products/", headers=headers, timeout=15)
        except Exception:
            pass
        elapsed_ms = (time.monotonic() - start) * 1000
        times.append(elapsed_ms)

        if (i + 1) % 25 == 0:
            log(f"{i + 1}/{n} Requests gesendet")

    return times


def query_jaeger(service: str) -> tuple[int, int]:
    """
    Fragt die Jaeger API ab.
    Gibt (total_traces, outlier_traces) zurueck.
    Outlier = mindestens ein Span laenger als OUTLIER_THRESHOLD_MS.
    """
    try:
        r = requests.get(
            f"{JAEGER}/api/traces",
            params={"service": service, "limit": 2000},
            timeout=15,
        )
        traces = r.json().get("data", [])
    except Exception as e:
        log(f"Jaeger API Fehler: {e}")
        return 0, 0

    total = len(traces)
    outliers = 0

    for trace in traces:
        for span in trace.get("spans", []):
            if span["duration"] > OUTLIER_THRESHOLD_MS * 1000:  # µs → ms
                outliers += 1
                break

    return total, outliers


def query_prometheus(metric: str) -> float | None:
    """Fragt eine Prometheus instant query ab und gibt den Wert zurueck."""
    try:
        r = requests.get(
            f"{PROMETHEUS}/api/v1/query",
            params={"query": metric},
            timeout=5,
        )
        result = r.json().get("data", {}).get("result", [])
        if result:
            return float(result[0]["value"][1])
    except Exception:
        pass
    return None


def query_prometheus_resource() -> dict:
    """Liest CPU und Memory des otelcol aus Prometheus."""
    cpu = query_prometheus('rate(otelcol_process_cpu_seconds[1m])')
    mem = query_prometheus('otelcol_process_memory_rss')
    spans_received = query_prometheus('rate(otelcol_receiver_accepted_spans[1m])')
    spans_exported = query_prometheus('rate(otelcol_exporter_sent_spans[1m])')
    return {
        "otelcol_cpu_rate":       round(cpu, 4)             if cpu is not None else None,
        "otelcol_mem_mb":         round(mem / 1024 / 1024)  if mem is not None else None,
        "spans_received_per_s":   round(spans_received, 1)  if spans_received is not None else None,
        "spans_exported_per_s":   round(spans_exported, 1)  if spans_exported is not None else None,
    }


# ── Experiment ────────────────────────────────────────────────────────────────

def run_strategy(strategy: dict, baseline_outliers: int | None = None) -> dict:
    name  = strategy["name"]
    label = strategy["label"]

    print(f"\n{'=' * 55}")
    print(f"  {label}")
    print(f"{'=' * 55}")

    env_overrides = {
        "SAMPLING_STRATEGY":         strategy.get("SAMPLING_STRATEGY", "always_on"),
        "SAMPLING_HEAD_RATE":        strategy.get("SAMPLING_HEAD_RATE", "0.1"),
        "OTELCOL_CONFIG":            strategy.get("OTELCOL_CONFIG", "passthrough"),
        "TAIL_LATENCY_THRESHOLD_MS": strategy.get("TAIL_LATENCY_THRESHOLD_MS", "500"),
        "LATENCY_SPORADIC_ENABLED":  "true",
        "LATENCY_SPORADIC_FIXED_MS": str(SPORADIC_FIXED_MS),
    }

    log("ENV aktualisieren...")
    update_env(env_overrides)

    clear_jaeger()
    restart_services()

    if not wait_for_gateway():
        return {"name": name, "label": label, "error": "gateway timeout"}

    time.sleep(3)  # OTel braucht einen Moment zum Initialisieren

    log("Admin sicherstellen...")
    ensure_admin()

    log(f"{N_REQUESTS} Requests senden (jeder {SPORADIC_EVERY_N}. = Spike)...")
    times = send_requests(N_REQUESTS)

    # Tail-based braucht extra Wartezeit: 15s decision_wait + ~5s batch flush
    extra_wait = 30 if strategy.get("OTELCOL_CONFIG") == "tail" else 5
    log(f"Warte {extra_wait}s auf Trace-Verarbeitung...")
    time.sleep(extra_wait)

    log("Jaeger auswerten...")
    total_traces, outliers_in_jaeger = query_jaeger("product-service")

    log("Prometheus auswerten...")
    prom = query_prometheus_resource()

    # Hilfswerte aus Client-Messungen
    actual_slow = sum(1 for t in times if t > OUTLIER_THRESHOLD_MS)
    avg_ms      = sum(times) / len(times)
    sorted_t    = sorted(times)
    p95_ms      = sorted_t[int(len(sorted_t) * 0.95)]
    p99_ms      = sorted_t[int(len(sorted_t) * 0.99)]

    # Detection Rate: Anteil der client-seitig langsamen Requests die in Jaeger auftauchen.
    # slow_requests_client ist die Ground Truth — unabhängig vom Server-Counter.
    if actual_slow > 0:
        detection_rate = round(outliers_in_jaeger / actual_slow * 100, 1)
    else:
        detection_rate = 0.0

    result = {
        "name":                  name,
        "label":                 label,
        "strategy":              strategy.get("SAMPLING_STRATEGY"),
        "head_rate":             strategy.get("SAMPLING_HEAD_RATE", "-"),
        "n_requests":            N_REQUESTS,
        "slow_requests_client":  actual_slow,
        "traces_in_jaeger":      total_traces,
        "outliers_in_jaeger":    outliers_in_jaeger,
        "detection_rate_pct":    detection_rate,
        "avg_response_ms":       round(avg_ms, 1),
        "p95_response_ms":             round(p95_ms, 1),
        "p99_response_ms":             round(p99_ms, 1),
        **prom,
    }

    log(f"Traces in Jaeger:  {total_traces}")
    log(f"Ausreißer (Client): {actual_slow}")
    log(f"Ausreißer (Jaeger): {outliers_in_jaeger}")
    log(f"Detection Rate:     {detection_rate:.1f}%")

    return result


def save_csv(results: list[dict], path: str):
    fieldnames = [
        "name", "label", "strategy", "head_rate",
        "n_requests", "slow_requests_client",
        "traces_in_jaeger", "outliers_in_jaeger",
        "detection_rate_pct",
        "avg_response_ms", "p95_response_ms", "p99_response_ms",
        "otelcol_cpu_rate", "otelcol_mem_mb",
        "spans_received_per_s", "spans_exported_per_s",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)


def print_table(results: list[dict]):
    print(f"\n{'=' * 80}")
    print(f"  ERGEBNISSE")
    print(f"{'=' * 80}")
    header = f"{'Strategie':<22} {'Traces':<8} {'Ausreißer':<11} {'Detection':<12} {'P95 ms'}"
    print(header)
    print("-" * 65)
    for r in results:
        if "error" in r:
            print(f"{r['label']:<22}  ERROR: {r['error']}")
            continue
        print(
            f"{r['label']:<22} "
            f"{r['traces_in_jaeger']:<8} "
            f"{r['outliers_in_jaeger']:<11} "
            f"{r['detection_rate_pct']:>6.1f}%      "
            f"{r['p95_response_ms']:.0f}"
        )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  BA2 Experiment: Sampling Strategy Evaluation")
    print("=" * 55)
    print(f"  Requests pro Strategie : {N_REQUESTS}")
    print(f"  Spikes                 : jeder {SPORADIC_EVERY_N}. Request → exakt {N_REQUESTS // SPORADIC_EVERY_N} Ausreißer")
    print(f"  Spike-Dauer            : {SPORADIC_FIXED_MS}ms (fix)")
    print(f"  Outlier-Schwelle       : {OUTLIER_THRESHOLD_MS}ms")
    print(f"  Strategien             : {len(STRATEGIES)}")

    build_services()
    log("Warte 10s nach Build...")
    time.sleep(10)

    results = []
    baseline_outliers = None

    for strategy in STRATEGIES:
        result = run_strategy(strategy, baseline_outliers)
        results.append(result)

        if strategy["name"] == "always_on" and "error" not in result:
            baseline_outliers = result.get("outliers_in_jaeger", 0)
            log(f"Baseline gesetzt: {baseline_outliers} Ausreißer")

    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(results_dir, exist_ok=True)
    csv_path    = os.path.join(results_dir, f"results_{timestamp}.csv")
    save_csv(results, csv_path)

    print_table(results)
    print(f"\n  CSV gespeichert: {csv_path}")


if __name__ == "__main__":
    main()
