import os
from typing import Optional, List
from sqlalchemy import or_
from fastapi import FastAPI, Depends, HTTPException, status, Request, Response, Query
from fastapi.middleware.cors import CORSMiddleware
import os
import httpx
import logging
import time
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response as FastAPIResponse


# forward Python logs to central log service (best-effort)
def setup_logging():
    log_url = os.getenv("LOG_SERVICE_URL")
    if not log_url:
        return

    class HTTPLogHandler(logging.Handler):
        def emit(self, record):
            try:
                payload = {
                    "service": "product-service",
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
logger = logging.getLogger("product-service")
from fastapi.responses import JSONResponse
from sqlmodel import Field, Session, SQLModel, create_engine, select
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
from datetime import datetime, timezone

# sensible defaults for local development to avoid crashes on import
DATABASE_URL = os.environ["DATABASE_URL"]
SECRET_KEY = SECRET_KEY or os.getenv("DEFAULT_SECRET_KEY", "dev_secret")
ALGORITHM = ALGORITHM or os.getenv("DEFAULT_ALGORITHM", "HS256")
import os as _os
AUTH_TOKEN_URL = _os.getenv("AUTH_TOKEN_URL", "http://localhost:8002/token")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=AUTH_TOKEN_URL)


class ProductBase(SQLModel):
    name: str
    description: Optional[str] = None
    price: float


class Product(ProductBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class ProductCreate(ProductBase):
    pass


class ProductRead(ProductBase):
    id: int


class ProductUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None


engine = create_engine(DATABASE_URL, echo=True)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


app = FastAPI(title="Product Service")

# allow browser-based frontend to call APIs in development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics (basic)
SERVICE_NAME = os.getenv("SERVICE_NAME", "product")
REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["method", "path", "status", "service"])
REQUEST_LATENCY = Histogram("http_request_latency_seconds", "Request latency in seconds", ["method", "path", "service"])


@app.middleware("http")
async def metrics_middleware(request, call_next):
    start = time.time()
    try:
        response = await call_next(request)
    except Exception as exc:
        # ensure we record exceptions as 500
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
def on_startup():
    create_db_and_tables()


def get_session():
    with Session(engine) as session:
        yield session


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role", "user")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return {"username": username, "role": role}


@app.exception_handler(HTTPException)
def http_exception_handler(request: Request, exc: HTTPException):
    try:
        if exc.status_code >= 500:
            logger.error("HTTPException %s %s %s", request.method, request.url.path, exc.detail, exc_info=True)
        else:
            logger.warning("HTTPException %s %s %s", request.method, request.url.path, exc.detail)
    except Exception:
        pass
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "http_exception", "detail": exc.detail},
    )


@app.exception_handler(Exception)
def generic_exception_handler(request: Request, exc: Exception):
    try:
        logger.error("Unhandled exception during request %s %s", request.method, request.url.path, exc_info=True)
    except Exception:
        pass
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "detail": str(exc)},
    )


@app.get("/health")
def health():
    return {"status": "UP", "time": datetime.now(timezone.utc).isoformat()}


@app.post("/products/", response_model=ProductRead)
def create_product(
        product: ProductCreate,
        session: Session = Depends(get_session),
        current_user: dict = Depends(get_current_user)
):
    # only admin can create products
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin_required")
    db_product = Product.from_orm(product)
    session.add(db_product)
    session.commit()
    session.refresh(db_product)
    # send log event (best-effort)
    try:
        log_url = os.getenv("LOG_SERVICE_URL")
        if log_url:
            httpx.post(f"{log_url}/logs", json={
                "service": "product-service",
                "event": "create_product",
                "user": current_user.get("username"),
                "product": {"id": db_product.id, "name": db_product.name},
            }, timeout=2.0)
    except Exception as e:
        logger.warning("Failed to send create_product log to log-service: %s", e)
    return db_product


@app.get("/products/", response_model=List[ProductRead])
def read_products(
    q: Optional[str] = Query(None, description="Search term"),
    session: Session = Depends(get_session),
):

    stmt = select(Product)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(Product.name.ilike(pattern), Product.description.ilike(pattern)))

    # get total count
    items = session.exec(stmt).all()


    return items


@app.get("/products/{product_id}", response_model=ProductRead)
def read_product(product_id: int, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.patch("/products/{product_id}", response_model=ProductRead)
def update_product(
        product_id: int,
        product_update: ProductUpdate,
        session: Session = Depends(get_session),
        current_user: dict = Depends(get_current_user)
):
    db_product = session.get(Product, product_id)
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")

    # only admin can update products
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin_required")

    product_data = product_update.dict(exclude_unset=True)
    for key, value in product_data.items():
        setattr(db_product, key, value)

    session.add(db_product)
    session.commit()
    session.refresh(db_product)
    try:
        log_url = os.getenv("LOG_SERVICE_URL")
        if log_url:
            httpx.post(f"{log_url}/logs", json={
                "service": "product-service",
                "event": "update_product",
                "user": current_user.get("username"),
                "product": {"id": db_product.id, "name": db_product.name},
            }, timeout=2.0)
    except Exception as e:
        logger.warning("Failed to send update_product log to log-service: %s", e)
    return db_product


@app.delete("/products/{product_id}")
def delete_product(
        product_id: int,
        session: Session = Depends(get_session),
        current_user: dict = Depends(get_current_user)
):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    # only admin can delete products
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin_required")
    session.delete(product)
    session.commit()
    try:
        log_url = os.getenv("LOG_SERVICE_URL")
        if log_url:
            httpx.post(f"{log_url}/logs", json={
                "service": "product-service",
                "event": "delete_product",
                "user": current_user.get("username"),
                "product": {"id": product_id},
            }, timeout=2.0)
    except Exception as e:
        logger.warning("Failed to send delete_product log to log-service: %s", e)
    return {"ok": True}


@app.get("/demo/logs")
def demo_logs():
    """Emit a demo WARN and ERROR to show up in the central log service."""
    logger.warning("Demo warning: this is a demo WARN from product-service")
    logger.error("Demo error: this is a demo ERROR from product-service")
    return {"ok": True, "msg": "logged demo WARN and ERROR"}


@app.get("/demo/raise")
def demo_raise():
    """Raise an exception to exercise the generic exception handler."""
    raise RuntimeError("Demo exception for testing error logging")