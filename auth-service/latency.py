"""Configurable latency injection for experiment scenarios.

Controlled via environment variables (all disabled by default):
  LATENCY_DB_DELAY_MS       – fixed sleep injected on every request (simulates slow DB)
  LATENCY_CPU_WORK_MS       – busy-loop CPU burn per request
  LATENCY_SPORADIC_ENABLED  – enable random sporadic spikes (true/false)
  LATENCY_SPORADIC_PROB     – probability of a spike per request (0.0–1.0, default 0.05)
  LATENCY_SPORADIC_MIN_MS   – min spike duration in ms (default 200)
  LATENCY_SPORADIC_MAX_MS   – max spike duration in ms (default 2000)
"""

import os
import time
import random

# ── configuration (read once at import) ──────────────────────────────

DB_DELAY_S = int(os.getenv("LATENCY_DB_DELAY_MS", "0")) / 1000.0
CPU_WORK_S = int(os.getenv("LATENCY_CPU_WORK_MS", "0")) / 1000.0
SPORADIC_ENABLED = os.getenv("LATENCY_SPORADIC_ENABLED", "false").lower() in ("1", "true", "yes")
SPORADIC_PROB = float(os.getenv("LATENCY_SPORADIC_PROB", "0.05"))
SPORADIC_MIN_S = int(os.getenv("LATENCY_SPORADIC_MIN_MS", "200")) / 1000.0
SPORADIC_MAX_S = int(os.getenv("LATENCY_SPORADIC_MAX_MS", "2000")) / 1000.0


def inject_latency():
    """Call at the beginning of a request to inject configured delays."""
    if DB_DELAY_S > 0:
        time.sleep(DB_DELAY_S)

    if CPU_WORK_S > 0:
        _cpu_burn(CPU_WORK_S)

    if SPORADIC_ENABLED and random.random() < SPORADIC_PROB:
        spike = random.uniform(SPORADIC_MIN_S, SPORADIC_MAX_S)
        time.sleep(spike)


def _cpu_burn(duration_s: float):
    """Busy-loop for *duration_s* seconds (burns CPU)."""
    end = time.monotonic() + duration_s
    while time.monotonic() < end:
        pass


# ── FastAPI middleware helper ────────────────────────────────────────

def add_latency_middleware(app):
    """Register an ASGI middleware that calls inject_latency() per request."""
    import asyncio

    @app.middleware("http")
    async def latency_middleware(request, call_next):
        # run blocking injection in a thread to not starve the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, inject_latency)
        return await call_next(request)
