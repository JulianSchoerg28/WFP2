import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import FastAPI, Depends, HTTPException, status, Request
import os
import httpx
import logging
import threading
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
                    "service": "auth-service",
                    "level": record.levelname,
                    "message": record.getMessage(),
                }
                # non-blocking best-effort
                threading.Thread(target=lambda: safe_post(f"{log_url}/logs", payload, timeout=1.0), daemon=True).start()
            except Exception:
                pass

    handler = HTTPLogHandler()
    handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)


setup_logging()
logger = logging.getLogger("auth-service")
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Field, Session, SQLModel, create_engine, select
from sqlalchemy.exc import IntegrityError
from fastapi import Header
from sqlmodel import select
from passlib.context import CryptContext
from jose import JWTError, jwt

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))


class UserBase(SQLModel):
    username: str = Field(index=True, unique=True)


class User(UserBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    hashed_password: str
    role: str = "user"


class UserCreate(UserBase):
    password: str


class UserRead(UserBase):
    id: int




class Token(SQLModel):
    access_token: str
    token_type: str


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL, echo=True)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


app = FastAPI(title="Authentication Service")

origins = [
    "http://localhost:8001",
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics (basic)
SERVICE_NAME = os.getenv("SERVICE_NAME", "auth")
REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["method", "path", "status", "service"])
REQUEST_LATENCY = Histogram("http_request_latency_seconds", "Request latency in seconds", ["method", "path", "service"])


@app.middleware("http")
async def metrics_middleware(request, call_next):
    start = time.time()
    try:
        response = await call_next(request)
    except Exception as exc:
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
    # ensure required environment variables are present for production
    if not SECRET_KEY or not ALGORITHM:
        raise RuntimeError("SECRET_KEY and ALGORITHM must be set in environment")
    create_db_and_tables()


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


def get_session():
    with Session(engine) as session:
        yield session


def safe_post(url: str, payload: dict, timeout: float = 2.0):
    try:
        httpx.post(url, json=payload, timeout=timeout)
    except Exception as e:
        logger.warning("safe_post failed for %s: %s", url, e)


@app.post("/register/", response_model=UserRead)
def register_user(user: UserCreate, session: Session = Depends(get_session)):
    # basic password policy
    pw = user.password or ""
    if len(pw) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if pw.isalpha() or pw.isdigit():
        raise HTTPException(status_code=400, detail="Password must include letters and numbers/symbols")

    hashed_password = get_password_hash(pw)
    # always create normal users via public registration
    db_user = User(username=user.username, hashed_password=hashed_password, role="user")
    session.add(db_user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=400, detail="Username already registered")
    session.refresh(db_user)
    # log registration
    try:
        log_url = os.getenv("LOG_SERVICE_URL")
        if log_url:
            threading.Thread(target=lambda: safe_post(f"{log_url}/logs", {
                "service": "auth-service",
                "event": "register",
                "user": db_user.username,
                "role": db_user.role,
            }, 2.0), daemon=True).start()
    except Exception as e:
        logger.warning("Failed to enqueue register log: %s", e)
    return db_user



@app.post('/auth/register', response_model=UserRead)
def register_user_alias(user: UserCreate, session: Session = Depends(get_session)):
    return register_user(user, session)


@app.post('/internal/create_admin', response_model=UserRead)
def create_admin_internal(
    user: UserCreate,
    x_internal_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
):
    # require internal API key for creating admin accounts
    expected = os.getenv("INTERNAL_API_KEY")
    if expected and x_internal_key != expected:
        raise HTTPException(status_code=403, detail="Forbidden")

    pw = user.password or ""
    if len(pw) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if pw.isalpha() or pw.isdigit():
        raise HTTPException(status_code=400, detail="Password must include letters and numbers/symbols")

    hashed_password = get_password_hash(pw)
    # create or upgrade existing user to admin
    existing = session.exec(select(User).where(User.username == user.username)).first()
    if existing:
        existing.hashed_password = hashed_password
        existing.role = "admin"
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    db_user = User(username=user.username, hashed_password=hashed_password, role="admin")
    session.add(db_user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=400, detail="Could not create admin")
    session.refresh(db_user)
    return db_user


@app.post("/token", response_model=Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.username == form_data.username)).first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": getattr(user, "role", "user")},
        expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "bearer"}


@app.post('/auth/logged_in')
def log_login_event(username: str):
    try:
        log_url = os.getenv("LOG_SERVICE_URL")
        if log_url:
            threading.Thread(target=lambda: safe_post(f"{log_url}/logs", {
                "service": "auth-service",
                "event": "login",
                "user": username,
            }, 2.0), daemon=True).start()
    except Exception as e:
        logger.warning("Failed to enqueue login log: %s", e)
    return {"status": "ok"}



@app.post('/auth/login', response_model=Token)
def login_alias(form_data: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)):
    return login_for_access_token(form_data, session)