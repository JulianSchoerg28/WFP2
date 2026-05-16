"""Configurable latency injection for experiment scenarios.

Controlled via environment variables (all disabled by default):
  LATENCY_SPORADIC_ENABLED  – enable spike injection (true/false)
  LATENCY_SPORADIC_FIXED_MS – fixed spike duration in ms (default 1000)

Spikes are triggered by the X-Inject-Latency: true request header,
set by the experiment script on every N-th request.
"""

import os
import time

SPORADIC_ENABLED = os.getenv("LATENCY_SPORADIC_ENABLED", "false").lower() in ("1", "true", "yes")
SPORADIC_FIXED_S = int(os.getenv("LATENCY_SPORADIC_FIXED_MS", "1000")) / 1000.0


def inject_latency():
    time.sleep(SPORADIC_FIXED_S)


def add_latency_middleware(app):
    import asyncio

    @app.middleware("http")
    async def latency_middleware(request, call_next):
        if SPORADIC_ENABLED and request.headers.get("x-inject-latency") == "true":
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, inject_latency)
        return await call_next(request)
