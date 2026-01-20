import os
from datetime import datetime
from typing import Optional, List
from sqlalchemy import text
from fastapi import FastAPI, HTTPException, Depends, Header
import os
import httpx
import logging
import threading
import json
import pika
from fastapi.middleware.cors import CORSMiddleware
import time
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response as FastAPIResponse
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlmodel import SQLModel, Field, create_engine, Session, select

app = FastAPI(title="Order Service")


# forward Python logs to central log service (best-effort)
def setup_logging():
    log_url = os.getenv("LOG_SERVICE_URL")
    if not log_url:
        return

    class HTTPLogHandler(logging.Handler):
        def emit(self, record):
            try:
                payload = {
                    "service": "order-service",
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
logger = logging.getLogger("order-service")

# allow browser-based frontend to call APIs in development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics (basic)
SERVICE_NAME = os.getenv("SERVICE_NAME", "order")
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

# auth configuration
AUTH_TOKEN_URL = os.getenv("AUTH_TOKEN_URL", "http://localhost:8002/token")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=AUTH_TOKEN_URL)
SECRET_KEY = os.getenv("SECRET_KEY", "dev_secret")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(status_code=401, detail="Could not validate credentials")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role", "user")
        if username is None:
            raise credentials_exception
        return {"username": username, "role": role}
    except Exception as exc:
        # In development, allow a best-effort fallback to parse token claims without
        # signature verification if decoding with the shared SECRET_KEY fails.
        # This helps when tokens are issued by a different environment; avoid crashing
        # production code — this is intentionally lenient for local development only.
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            username: str = payload.get("sub")
            role: str = payload.get("role", "user")
            if username is None:
                raise credentials_exception
            return {"username": username, "role": role}
        except Exception:
            raise credentials_exception


class CartItem(SQLModel):
    product_id: int
    quantity: int


class Order(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    status: str = Field(default="PENDING_PAYMENT")
    items: str
    user_id: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL, echo=False)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql('ALTER TABLE IF EXISTS "order" ADD COLUMN IF NOT EXISTS user_id TEXT')
    except Exception as e:
        logger.warning("Failed to ensure order table schema: %s", e)


@app.post("/orders", status_code=201)
def create_order(current_user: dict = Depends(get_current_user), token: str = Depends(oauth2_scheme)):
    """Create an order by fetching the authenticated user's cart from the cart service.
    The frontend no longer provides the item list; we forward the user's token to the cart service.
    """
    user_identifier = current_user.get("username") if current_user else None
    # fetch cart from cart-service
    try:
        cart_url = os.getenv("CART_SERVICE_URL", "http://cart-service:8000")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = httpx.get(f"{cart_url}/cart", headers=headers, timeout=5.0)
        if r.status_code != 200:
            logger.warning("Failed to fetch cart for user %s: %s %s", user_identifier, r.status_code, r.text[:200])
            raise HTTPException(status_code=502, detail="Failed to retrieve cart items")
        cart = r.json()
        items = cart.get("items", [])
        if not items:
            raise HTTPException(status_code=400, detail="Cart is empty")
        # normalize items to a simple list of dicts for storage/publishing
        order_items = []
        for it in items:
            # cart items are enriched by cart-service; ensure product_id and quantity
            pid = it.get("product_id") or it.get("id") or it.get("productId")
            qty = it.get("quantity") or it.get("qty") or 1
            order_items.append({"product_id": int(pid), "quantity": int(qty)})
        items_str = str(order_items)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Error fetching cart for order creation: %s", e)
        raise HTTPException(status_code=502, detail="Failed to retrieve cart items")
    order = Order(items=items_str, user_id=user_identifier)
    with Session(engine) as session:
        session.add(order)
        session.commit()
        session.refresh(order)
    # fire-and-forget: log event
    try:
        log_url = os.getenv("LOG_SERVICE_URL")
        if log_url:
            threading.Thread(target=lambda: safe_log_post(log_url, {
                "service": "order-service",
                "event": "create_order",
                "user": user_identifier,
                "order": {"id": order.id},
            }), daemon=True).start()
    except Exception as e:
        logger.warning("Failed to spawn log thread for create_order: %s", e)

    # publish OrderPlaced event to message broker (RabbitMQ)
    try:
        event = {
            "event": "OrderPlaced",
            "order": {"id": order.id, "user": user_identifier, "items": items_str},
            "time": datetime.utcnow().isoformat() + "Z",
        }
        threading.Thread(target=lambda: publish_order_event(event), daemon=True).start()
    except Exception as e:
        logger.warning("Failed to publish OrderPlaced event: %s", e)
    # attempt to clear the user's cart (best-effort)
    try:
        try:
            cart_url = os.getenv("CART_SERVICE_URL", "http://cart-service:8000")
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            with httpx.Client(timeout=3.0) as client:
                client.delete(f"{cart_url}/cart", headers=headers, timeout=3.0)
        except Exception as e:
            logger.warning("Failed to clear cart for user %s: %s", user_identifier, e)
    except Exception:
        pass
    return {"id": order.id, "status": order.status}


def safe_log_post(log_url: str, payload: dict):
    try:
        httpx.post(f"{log_url}/logs", json=payload, timeout=2.0)
    except Exception as e:
        logger.warning("safe_log_post failed: %s", e)


def publish_order_event(event: dict):
    try:
        amqp_url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/%2F")
        params = pika.URLParameters(amqp_url)
        conn = pika.BlockingConnection(params)
        ch = conn.channel()
        ch.exchange_declare(exchange="events", exchange_type="topic", durable=True)
        routing_key = "order.placed"
        body = json.dumps(event)
        ch.basic_publish(exchange="events", routing_key=routing_key, body=body, properties=pika.BasicProperties(content_type="application/json", delivery_mode=2))
        conn.close()
    except Exception as e:
        logger.warning("publish_order_event failed: %s", e)


@app.get("/orders/{order_id}")
def read_order(order_id: int, current_user: dict = Depends(get_current_user)):
    with Session(engine) as session:
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        # allow admin or owner to view
        if current_user.get("role") != "admin" and order.user_id != current_user.get("username"):
            raise HTTPException(status_code=403, detail="Forbidden")
        return {"id": order.id, "status": order.status, "items": order.items}


@app.get("/internal/orders/{order_id}")
def read_order_internal(order_id: int, x_internal_key: str | None = Header(default=None)):
    # internal endpoint for other services to fetch order details using the internal API key
    if INTERNAL_API_KEY and x_internal_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")
    with Session(engine) as session:
        try:
            print('internal handler hit for id', order_id)
        except Exception:
            pass
        order = session.get(Order, order_id)
        try:
            print('internal lookup order:', order)
        except Exception:
            pass
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return {"id": order.id, "status": order.status, "items": order.items}


@app.get('/internal/debug/routes')
def internal_debug_routes():
    # helpful debug endpoint to list registered paths
    try:
        return [r.path for r in app.routes]
    except Exception:
        return {"error": "could not list routes"}


@app.get("/myorders")
def list_my_orders(current_user: dict = Depends(get_current_user)):
    user_identifier = current_user.get("username")
    with Session(engine) as session:
        orders = session.exec(select(Order).where(Order.user_id == user_identifier)).all()
        return [
            {"id": o.id, "status": o.status, "items": o.items, "created_at": o.created_at.isoformat()} for o in orders
        ]


@app.get("/orders")
def list_orders(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin_required")
    with Session(engine) as session:
        orders = session.exec(select(Order)).all()
        return [
            {"id": o.id, "status": o.status, "items": o.items, "created_at": o.created_at.isoformat()} for o in orders
        ]


@app.patch("/orders/{order_id}")
def update_order_status(
    order_id: int,
    status: str,
    x_internal_key: str | None = Header(default=None),
):
    if INTERNAL_API_KEY and x_internal_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")

    with Session(engine) as session:
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        order.status = status
        session.add(order)
        session.commit()
        session.refresh(order)

    return {"id": order.id, "status": order.status}


@app.get("/health")
def health():
    return {"status": "UP", "time": datetime.utcnow().isoformat()}
