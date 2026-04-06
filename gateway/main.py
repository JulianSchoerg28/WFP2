import os
from tracing import setup_tracing, instrument_app
setup_tracing()

from datetime import datetime
from typing import Optional

import httpx
import asyncio
import json
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose import jwt
import logging
import threading

SECRET_KEY = os.environ.get("SECRET_KEY", "dev_secret")
ALGORITHMS = ["HS256"]

app = FastAPI(title="API Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

instrument_app(app)

logger = logging.getLogger("api-gateway")


def verify_jwt_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=ALGORITHMS, options={"verify_aud": False})
        return payload
    except Exception:
        return None


def select_upstream(path: str) -> Optional[str]:
    # Round-robin upstream pool selection.
    # Upstreams can be configured via environment variables, comma-separated, e.g.
    # PRODUCT_UPSTREAMS=http://product-a:8000,http://product-b:8000
    p = path.lstrip("/")

    # define mapping of path prefix -> env var name and default
    mapping = [
        ("products", "PRODUCT_UPSTREAMS", "http://product-service:8000"),
        ("auth", "AUTH_UPSTREAMS", "http://auth-service:8000"),
        ("token", "AUTH_UPSTREAMS", "http://auth-service:8000"),
        ("orders", "ORDER_UPSTREAMS", "http://order-service:8000"),
        ("myorders", "ORDER_UPSTREAMS", "http://order-service:8000"),
        ("payment", "PAYMENT_UPSTREAMS", "http://payment-service:8000"),
        ("cart", "CART_UPSTREAMS", "http://cart-service:8000"),
        ("logs", "LOG_UPSTREAMS", "http://log-service:8000"),
        ("events", "LOG_UPSTREAMS", "http://log-service:8000"),
        ("log", "LOG_UPSTREAMS", "http://log-service:8000"),
    ]

    for prefix, envname, default in mapping:
        if p.startswith(prefix):
            upstreams = os.getenv(envname, default)
            # split and strip
            pool = [u.strip() for u in upstreams.split(",") if u.strip()]
            if not pool:
                return None
            # initialize counters/locks on first access
            key = envname
            if key not in _upstream_counters:
                # protect init with global lock
                with _upstream_init_lock:
                    if key not in _upstream_counters:
                        _upstream_counters[key] = 0
                        _upstream_locks[key] = threading.Lock()
                        _upstream_pools[key] = pool
            # if pool changed (e.g., updated env), refresh list
            if _upstream_pools.get(key) != pool:
                with _upstream_locks[key]:
                    _upstream_pools[key] = pool
                    _upstream_counters[key] = 0

            # select next upstream using round-robin
            with _upstream_locks[key]:
                # prefer upstreams that are known healthy; fall back to full pool
                candidates = list(_upstream_pools[key])
                any_healthy = any(_upstream_status.get(u) for u in candidates)
                if any_healthy:
                    pool_for_selection = [u for u in candidates if _upstream_status.get(u)]
                else:
                    pool_for_selection = candidates

                idx = _upstream_counters[key]
                upstream = pool_for_selection[idx % len(pool_for_selection)]
                _upstream_counters[key] = (idx + 1) % len(pool_for_selection)
            return upstream

    return None


# upstream pool state (keyed by ENV var name)
_upstream_pools: dict = {}
_upstream_counters: dict = {}
_upstream_locks: dict = {}
_upstream_init_lock = threading.Lock()
_upstream_status: dict = {}  # maps upstream URL -> healthy(bool)
HEALTH_CHECK_INTERVAL = float(os.getenv("UPSTREAM_HEALTH_INTERVAL", "5.0"))
HEALTH_CHECK_TIMEOUT = float(os.getenv("UPSTREAM_HEALTH_TIMEOUT", "1.0"))


def _check_upstream_once(key: str):
    """Ping /health on all upstreams for a given pool key and update _upstream_status."""
    pool = _upstream_pools.get(key, [])
    for u in list(pool):
        url = u.rstrip("/") + "/health"
        healthy = False
        try:
            with httpx.Client(timeout=HEALTH_CHECK_TIMEOUT) as client:
                r = client.get(url)
                healthy = 200 <= r.status_code < 300
        except Exception:
            healthy = False
        _upstream_status[u] = healthy


def _health_check_loop():
    while True:
        try:
            keys = list(_upstream_pools.keys())
            for k in keys:
                # perform check for this pool
                try:
                    _check_upstream_once(k)
                except Exception:
                    pass
        except Exception:
            pass
        time_to_sleep = HEALTH_CHECK_INTERVAL
        try:
            # sleep in small increments to be more responsive to shutdown if needed
            total = 0.0
            while total < time_to_sleep:
                threading.Event().wait(min(0.5, time_to_sleep - total))
                total += 0.5
        except Exception:
            pass


@app.on_event("startup")
def _start_health_thread():
    t = threading.Thread(target=_health_check_loop, daemon=True)
    t.start()


_log_base = os.getenv("LOG_SERVICE_URL", "http://log-service:8000")
LOG_EVENTS_URL = _log_base.rstrip("/") + "/logs"


async def send_log_event(payload: dict):
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            # best-effort POST to log service
            await client.post(LOG_EVENTS_URL, json=payload)
    except Exception:
        return


@app.get("/health")
async def health():
    return {"status": "UP", "time": datetime.utcnow().isoformat()}


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy(full_path: str, request: Request):
    upstream = select_upstream(full_path)
    if not upstream:
        try:
            logger.warning("No upstream for path %s", full_path)
        except Exception:
            pass
        return JSONResponse(status_code=502, content={"error": "no upstream for path"})
    
    forward_path = full_path
    path_no_slash = full_path.lstrip("/").lower()

    if upstream and (path_no_slash.startswith("auth/internal/") or path_no_slash.startswith("auth/register") or path_no_slash.startswith("auth/login")):
        forward_path = full_path[len("auth/"):]

    if path_no_slash.endswith("/health"):
        forward_path = "health"
    if path_no_slash.endswith("/metrics"):
        forward_path = "metrics"

    url = f"{upstream}/{forward_path}"

    # Debug: log the exact upstream URL for auth register attempts
    try:
        if full_path.lower().startswith("auth/register"):
            try:
                print(f"gateway -> upstream url: {url}")
            except Exception:
                logger.warning("gateway -> upstream url: %s", url)
    except Exception:
        pass

    headers = dict(request.headers)
    # remove host header to avoid upstream confusion
    headers.pop("host", None)

    # validate token if present and forward user identity
    auth = headers.get("authorization") or headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(None, 1)[1]
        payload = verify_jwt_token(token)
        if payload:
            user_id = payload.get("sub") or payload.get("username") or payload.get("user_id")
            if user_id:
                headers["x-user-id"] = str(user_id)

    # add marker header so upstream knows request passed the gateway
    headers["x-forwarded-by"] = "api-gateway"

    # enforce admin-only paths: product mutations
    admin_methods = {"POST", "PUT", "PATCH", "DELETE"}
    path_lower = full_path.lower()
    is_product_mutation = path_lower.startswith("products") and request.method in admin_methods
    if is_product_mutation:
        payload = None
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(None, 1)[1]
            payload = verify_jwt_token(token)

        def is_admin(p: Optional[dict]) -> bool:
            if not p:
                return False
            if p.get("is_admin"):
                return True
            role = p.get("role") or p.get("roles")
            if isinstance(role, str) and role.lower() == "admin":
                return True
            if isinstance(role, (list, tuple)) and "admin" in [r.lower() for r in role if isinstance(r, str)]:
                return True
            return False

        if not is_admin(payload):
            try:
                logger.warning("Admin privileges required for %s %s (user=%s)", request.method, full_path, payload)
            except Exception:
                pass
            return JSONResponse(status_code=403, content={"error": "admin privileges required"})

    body = await request.body()
    # debug: log raw proxied body for payment paths to diagnose malformed requests
    try:
        if full_path.lower().startswith("payment"):
            try:
                logger.warning("gateway raw body for %s: %s", full_path, body[:1000])
            except Exception:
                pass
            try:
                # also print so container logs capture regardless of logger config
                print(f"gateway raw body for {full_path}: {body[:1000]}")
            except Exception:
                pass
    except Exception:
        pass

    from urllib.parse import urlparse

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            
            resp = await client.request(
                request.method,
                url,
                headers=headers,
                params=request.query_params,
                content=body,
                follow_redirects=False,
            )
            if resp.status_code in (301, 302, 307, 308) and "location" in resp.headers:
                try:
                    loc = resp.headers.get("location")
                    logger.warning("upstream responded with redirect: %s -> %s", url, loc)
                    parsed = urlparse(loc)
                    # build a follow URL that targets the same upstream
                    follow_path = parsed.path or ""
                    if parsed.query:
                        follow_path = follow_path + "?" + parsed.query
                    follow_url = f"{upstream}/{follow_path.lstrip('/')}"
                    logger.warning("rewritten follow_url: %s", follow_url)
                    follow_resp = await client.request(
                        request.method,
                        follow_url,
                        headers=headers,
                        params=request.query_params,
                        content=body,
                        follow_redirects=True,
                    )
                    logger.warning("followed redirect, status=%s, snippet=%s", follow_resp.status_code, (follow_resp.text or '')[:200])
                    resp = follow_resp
                except Exception as e:
                    logger.error("failed to follow upstream redirect for %s -> %s: %s", url, loc if 'loc' in locals() else None, e, exc_info=True)
        except httpx.RequestError as exc:
            try:
                logger.error("Upstream request failed for %s -> %s: %s", url, full_path, exc, exc_info=True)
            except Exception:
                pass
            return JSONResponse(status_code=502, content={"error": f"upstream request failed: {exc}"})

    # fire-and-forget log event about proxied request
    try:
        user = headers.get("x-user-id") or headers.get("x-user") or None
        event = {
            "service": "api-gateway",
            "level": "INFO",
            "time": datetime.utcnow().isoformat() + "Z",
            "path": f"/{full_path}",
            "method": request.method,
            "status": resp.status_code,
            "user": user,
        }
        asyncio.create_task(send_log_event(event))
    except Exception:
        pass

    response_headers = {k: v for k, v in resp.headers.items() if k.lower() not in ("content-encoding", "transfer-encoding", "connection")}
    return Response(content=resp.content, status_code=resp.status_code, headers=response_headers)
