import os
import json
from datetime import datetime
from typing import Optional

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, Request, Query
import logging

import time
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response as FastAPIResponse

logger = logging.getLogger('log-service')

# prefer explicit LOG_DATABASE_URL, else fall back to DATABASE_URL or default
DB_DSN = os.getenv('LOG_DATABASE_URL') or os.getenv('DATABASE_URL') or (
    f"postgresql://{os.getenv('POSTGRES_USER','postgres')}:{os.getenv('POSTGRES_PASSWORD','postgres')}@db:5432/logs_db"
)


def init_db():
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY,
                ts TIMESTAMPTZ NOT NULL,
                service TEXT,
                level TEXT,
                event TEXT,
                payload JSONB
            )
            """
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error('Failed to initialize logs DB: %s', e, exc_info=True)


app = FastAPI(title='Central Log Service')


@app.on_event('startup')
def on_startup():
    init_db()


@app.post('/logs')
async def receive_log(req: Request):
    # accept JSON bodies when possible, but tolerate non-JSON safely
    try:
        payload = await req.json()
    except Exception:
        try:
            raw = await req.body()
            payload = {'_raw': raw.decode(errors='ignore')}
        except Exception:
            payload = {}

    level = payload.get('level') or payload.get('level_name') or 'INFO'
    service = payload.get('service') or payload.get('src') or 'unknown'
    event = payload.get('event') or payload.get('message') or 'log'
    ts = datetime.utcnow()
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        # use psycopg2.extras.Json so payload is stored as proper JSON/JSONB
        cur.execute(
            'INSERT INTO logs (ts, service, level, event, payload) VALUES (%s, %s, %s, %s, %s)',
            (ts, service, level, event, psycopg2.extras.Json(payload)),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error('Failed to persist log: %s', e, exc_info=True)

    logger.info('%s %s: %s', level, service, event)
    return {'status': 'received'}


@app.post('/')
async def receive_log_root(req: Request):
    return await receive_log(req)


@app.get('/events')
def get_events(level: Optional[str] = Query(None), limit: int = Query(100)):
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        if level:
            cur.execute(
                'SELECT ts, service, level, event, payload FROM logs WHERE level = %s ORDER BY id DESC LIMIT %s',
                (level.upper(), limit),
            )
        else:
            cur.execute('SELECT ts, service, level, event, payload FROM logs ORDER BY id DESC LIMIT %s', (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error('Failed to query logs: %s', e, exc_info=True)
        return []

    results = []
    for r in rows:
        ts = r[0].isoformat() if r[0] else None
        service = r[1]
        lvl = r[2]
        event = r[3]
        payload = r[4]
        results.append({'ts': ts, 'service': service, 'level': lvl, 'event': event, 'payload': payload})
    return results


@app.get('/health')
def health():
    return {'status': 'UP', 'time': datetime.utcnow().isoformat()}


# Prometheus metrics (basic)
SERVICE_NAME = os.getenv('SERVICE_NAME', 'log')
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'path', 'status', 'service'])
REQUEST_LATENCY = Histogram('http_request_latency_seconds', 'Request latency in seconds', ['method', 'path', 'service'])


@app.middleware('http')
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


@app.get('/metrics')
def metrics():
    data = generate_latest()
    return FastAPIResponse(content=data, media_type=CONTENT_TYPE_LATEST)
