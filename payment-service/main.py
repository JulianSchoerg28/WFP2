from datetime import datetime
from fastapi import FastAPI
import os
import httpx
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import httpx
import logging
import random

import time
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response as FastAPIResponse, Request


# forward Python logs to central log service (best-effort)
def setup_logging():
    log_url = os.getenv("LOG_SERVICE_URL")
    if not log_url:
        return

    class HTTPLogHandler(logging.Handler):
        def emit(self, record):
            try:
                payload = {
                    "service": "payment-service",
                    "level": record.levelname,
                    "message": record.getMessage(),
                }
                httpx.post(f"{log_url}/logs", json=payload, timeout=1.0)
            except Exception:
                pass

    handler = HTTPLogHandler()
    handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)


setup_logging()
logger = logging.getLogger("payment-service")

app = FastAPI(title="Payment Service")

# allow browser-based frontend to call APIs in development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics (basic)
SERVICE_NAME = os.getenv("SERVICE_NAME", "payment")
REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["method", "path", "status", "service"])
REQUEST_LATENCY = Histogram("http_request_latency_seconds", "Request latency in seconds", ["method", "path", "service"])


@app.middleware("http")
async def metrics_middleware(request, call_next):
    start = time.time()
    try:
        response = await call_next(request)
    except Exception:
        REQUEST_LATENCY.labels(request.method, request.url.path, SERVICE_NAME).observe(time.time() - start)
        REQUEST_COUNT.labels(request.method, request.url.path, 500, SERVICE_NAME).inc()
        raise
    duration = time.time() - start
    try:
        REQUEST_LATENCY.labels(request.method, request.url.path, SERVICE_NAME).observe(duration)
        REQUEST_COUNT.labels(request.method, request.url.path, response.status_code, SERVICE_NAME).inc()
    except Exception:
        pass
    return response


@app.get("/metrics")
def metrics():
    data = generate_latest()
    return FastAPIResponse(content=data, media_type=CONTENT_TYPE_LATEST)

# configuration
ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://localhost:8003")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
# Configure simulated payment success probability (0.0 - 1.0). Default 1.0 (always succeed).
try:
    PAYMENT_SUCCESS_RATE = float(os.getenv("PAYMENT_SUCCESS_RATE", "0.75"))
except Exception:
    PAYMENT_SUCCESS_RATE = 0.75


class PaymentResult(BaseModel):
    result: str


def _process_payment_logic(order_id: int, method: str | None = None) -> str:
    result = "FAILED"
    try:
        # use an internal read endpoint for GET so we can avoid OAuth token requirements
        get_url = f"{ORDER_SERVICE_URL}/internal/orders/{order_id}"
        patch_url = f"{ORDER_SERVICE_URL}/orders/{order_id}"
        headers = {}
        if INTERNAL_API_KEY:
            headers["X-Internal-Key"] = INTERNAL_API_KEY
        with httpx.Client(timeout=5.0) as client:
            # check current status (include internal header for inter-service auth)
            try:
                r_get = client.get(get_url, headers=headers, timeout=5.0)
            except Exception as e:
                logger.warning("Failed to GET order %s: %s", get_url, e)
                return "FAILED"

            # log GET status for debugging auth/404 issues (also print to stdout)
            try:
                logger.info("Order GET %s returned %s", get_url, r_get.status_code)
            except Exception:
                pass
            try:
                print("Order GET", get_url, "->", r_get.status_code)
                try:
                    print("Order GET body:", r_get.text[:1000])
                except Exception:
                    pass
            except Exception:
                pass

            if r_get.status_code != 200:
                # If we can't read the order via the internal GET, don't try to force-set PAID.
                # This avoids marking orders paid when the internal read is restricted or the order
                # does not exist yet. Let the caller/consumer handle retries asynchronously.
                logger.warning("Order GET returned %s for %s; aborting sync payment attempt", r_get.status_code, get_url)
                return "FAILED"

            try:
                current_status = r_get.json().get("status")
            except Exception:
                current_status = None

            if current_status == "PAID":
                # already paid -> idempotent success
                result = "SUCCESS"
            else:
                # simulate flaky payment according to PAYMENT_SUCCESS_RATE
                try:
                    rand_val = random.random()
                except Exception:
                    rand_val = 1.0
                if rand_val > PAYMENT_SUCCESS_RATE:
                    logger.info("Simulated payment failure for order %s (rand=%s rate=%s)", order_id, rand_val, PAYMENT_SUCCESS_RATE)
                    result = "FAILED"
                else:
                    # attempt to mark order as PAID
                    # reuse headers with internal key for the PATCH
                    try:
                        r_patch = client.patch(patch_url, params={"status": "PAID"}, headers=headers, timeout=5.0)
                        if 200 <= r_patch.status_code < 300:
                            result = "SUCCESS"
                        else:
                            logger.warning("PATCH to order failed: %s %s", r_patch.status_code, r_patch.text)
                            result = "FAILED"
                    except Exception as e:
                        logger.warning("Failed to PATCH order %s: %s", patch_url, e)
                        result = "FAILED"
    except Exception as e:
        logger.warning("Unexpected error during payment processing: %s", e)
        result = "FAILED"

    # send log event to central log service (best effort)
    try:
        log_url = os.getenv("LOG_SERVICE_URL")
        if log_url:
            httpx.post(f"{log_url}/logs", json={
                "service": "payment-service",
                "event": "process_payment",
                "order_id": order_id,
                "method": method,
                "result": result,
            }, timeout=2.0)
    except Exception as e:
        logger.warning("Failed to send process_payment log: %s", e)

    return result


@app.post("/payment", response_model=PaymentResult)
@app.post("/payments", response_model=PaymentResult)
async def process_payment(request: Request):
    # Tolerant parsing: accept JSON, form or query and coerce order_id
    try:
        data = {}
        # log raw body for debugging parsing/422 issues
        try:
            raw = await request.body()
            try:
                logger.warning("payment raw body: %s", raw[:500])
            except Exception:
                pass
            try:
                # also print to stdout so container logs capture it regardless of logger
                print("payment raw body:", raw[:500])
            except Exception:
                pass
        except Exception:
            raw = b""
        try:
            data = await request.json()
        except Exception:
            # try form data
            try:
                form = await request.form()
                data = dict(form)
            except Exception:
                data = {}

        # also allow query params
        if not data:
            for k, v in request.query_params.items():
                data[k] = v

        order_id = data.get("order_id") or data.get("orderId") or data.get("id")
        method = data.get("method") or data.get("payment_method")
        if order_id is None:
            return FastAPIResponse(content='{"result": "FAILED", "error": "missing order_id"}', status_code=422, media_type="application/json")
        try:
            order_id = int(order_id)
        except Exception:
            return FastAPIResponse(content='{"result": "FAILED", "error": "invalid order_id"}', status_code=422, media_type="application/json")

        result = _process_payment_logic(order_id, method)

        if result == "SUCCESS":
            return {"result": result}
        else:
            # Payment processing failed synchronously; return 202 Accepted (queued/pending)
            # so the frontend doesn't show an error while async retries/consumer can handle it.
            return FastAPIResponse(content='{"result": "PENDING"}', status_code=202, media_type="application/json")
    except Exception as e:
        logger.warning("Error parsing payment request: %s", e)
        return FastAPIResponse(content='{"result": "FAILED"}', status_code=400, media_type="application/json")


@app.get("/health")
def health():
    return {"status": "UP", "time": datetime.utcnow().isoformat()}
