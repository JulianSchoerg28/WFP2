from fastapi import FastAPI, Depends, HTTPException, Query
from typing import Optional
from datetime import datetime
import os
import httpx
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
import psycopg2
import requests
import os
import jwt
import logging


# forward Python logs to central log service (best-effort)
def setup_logging():
    log_url = os.getenv("LOG_SERVICE_URL")
    if not log_url:
        return

    class HTTPLogHandler(logging.Handler):
        def emit(self, record):
            try:
                payload = {
                    "service": "cart-service",
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

logger = logging.getLogger("cart-service")

import time
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response as FastAPIResponse

# Use shared auth env vars for compatibility
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
DATABASE_URL = os.environ.get("DATABASE_URL")
PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "http://product-service:8001")

app = FastAPI(title="Cart Service")
 
# allow browser-based frontend to call APIs in development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=os.getenv("AUTH_TOKEN_URL", "http://localhost:8002/token"))
    
# Prometheus metrics (basic)
SERVICE_NAME = os.getenv("SERVICE_NAME", "cart")
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
    
@app.on_event("startup")
def ensure_tables():
    """Create required tables if they don't exist. This helps when the DB was created without init SQL."""
    try:
        conn = get_db()
        if not conn:
            return
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cart_items (
                user_id TEXT NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                PRIMARY KEY (user_id, product_id)
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        # Do not crash startup if DB not yet reachable; service can retry later
        logger.warning("ensure_tables failed: %s", e)


def get_db():
    return psycopg2.connect(DATABASE_URL) if DATABASE_URL else None


def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        # decode using the shared SECRET_KEY/ALGORITHM to be compatible with auth-service tokens
        payload = jwt.decode(token, SECRET_KEY or os.getenv("JWT_SECRET"), algorithms=[ALGORITHM])
        username = payload.get("sub")
        role = payload.get("role", "user")
        return {"username": username, "role": role}
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.get("/health")
def health():
    return {"status": "UP", "time": datetime.utcnow().isoformat()}


def _insert_or_update_cart(conn, user_identifier, product_id, quantity):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO cart_items (user_id, product_id, quantity)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, product_id)
        DO UPDATE SET quantity = cart_items.quantity + EXCLUDED.quantity
    """, (user_identifier, product_id, quantity))
    conn.commit()
    cur.close()


@app.post("/cart/items")
def add_item_to_cart(body: dict, user: dict = Depends(get_current_user)):
    product_id = int(body.get("product_id"))
    quantity = int(body.get("quantity"))
    conn = get_db()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    user_identifier = user.get("username")
    _insert_or_update_cart(conn, user_identifier, product_id, quantity)
    conn.close()
    # log event
    try:
        log_url = os.getenv("LOG_SERVICE_URL")
        if log_url:
            httpx.post(f"{log_url}/logs", json={
                "service": "cart-service",
                "event": "add_item",
                "user": user_identifier,
                "product_id": product_id,
                "quantity": quantity,
            }, timeout=2.0)
    except Exception as e:
        logger.warning("Failed to send add_item log: %s", e)
    return {"message": "Item added to cart"}




@app.delete("/cart/items/{product_id}")
def delete_item_from_cart(
    product_id: int,
    quantity: Optional[int] = Query(None, ge=1),
    user: dict = Depends(get_current_user),
):
    """Delete an item from the cart or decrement its quantity when `quantity` is provided."""
    conn = get_db()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    cur = conn.cursor()
    user_identifier = user.get("username")

    try:
        if quantity is None:
            # remove entire row
            cur.execute(
                "DELETE FROM cart_items WHERE user_id = %s AND product_id = %s",
                (user_identifier, product_id)
            )
            conn.commit()
            removed = True
            remaining = 0
            resp = {"message": "Item removed from cart"}
        else:
            # fetch current quantity
            cur.execute(
                "SELECT quantity FROM cart_items WHERE user_id = %s AND product_id = %s",
                (user_identifier, product_id)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Item not found in cart")
            current_qty = row[0]
            new_qty = current_qty - quantity
            if new_qty > 0:
                cur.execute(
                    "UPDATE cart_items SET quantity = %s WHERE user_id = %s AND product_id = %s",
                    (new_qty, user_identifier, product_id)
                )
                conn.commit()
                removed = False
                remaining = new_qty
                resp = {"message": "Quantity decremented", "remaining": new_qty}
            else:
                cur.execute(
                    "DELETE FROM cart_items WHERE user_id = %s AND product_id = %s",
                    (user_identifier, product_id)
                )
                conn.commit()
                removed = True
                remaining = 0
                resp = {"message": "Item removed from cart"}
    finally:
        cur.close()
        conn.close()

    # emit best-effort log
    try:
        log_url = os.getenv("LOG_SERVICE_URL")
        if log_url:
            payload = {
                "service": "cart-service",
                "event": "remove_item",
                "user": user_identifier,
                "product_id": product_id,
                "removed_all": removed,
                "remaining": remaining,
            }
            httpx.post(f"{log_url}/logs", json=payload, timeout=2.0)
    except Exception as e:
        logger.warning("Failed to send remove_item log: %s", e)

    return resp




@app.get("/cart")
def get_cart(user: dict = Depends(get_current_user)):
    conn = get_db()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    cur = conn.cursor()
    user_identifier = user.get("username")
    cur.execute(
        "SELECT product_id, quantity FROM cart_items WHERE user_id = %s",
        (user_identifier,)
    )
    items = cur.fetchall()
    cur.close()
    conn.close()

    enriched_items = []
    subtotal = 0.0

    for product_id, qty in items:
        r = requests.get(f"{PRODUCT_SERVICE_URL}/products/{product_id}")
        if r.status_code != 200:
            continue

        product = r.json()
        item_total = product["price"] * qty
        subtotal += item_total

        enriched_items.append({
            "product_id": product_id,
            "name": product["name"],
            "price": product["price"],
            "quantity": qty,
            "total": item_total
        })

    shipping = 5.0 if subtotal > 0 else 0.0

    return {
        "items": enriched_items,
        "subtotal": subtotal,
        "shipping": shipping,
        "total": subtotal + shipping
    }


@app.delete("/cart")
def clear_cart(user: dict = Depends(get_current_user)):
    """Remove all items from the authenticated user's cart."""
    conn = get_db()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    cur = conn.cursor()
    user_identifier = user.get("username")
    try:
        cur.execute("DELETE FROM cart_items WHERE user_id = %s", (user_identifier,))
        conn.commit()
    finally:
        cur.close()
        conn.close()

    try:
        log_url = os.getenv("LOG_SERVICE_URL")
        if log_url:
            httpx.post(f"{log_url}/logs", json={
                "service": "cart-service",
                "event": "clear_cart",
                "user": user_identifier,
            }, timeout=2.0)
    except Exception as e:
        logger.warning("Failed to send clear_cart log: %s", e)

    return {"message": "Cart cleared"}
