# WFP2
# MicroShop

Note for Prof.: Had the project in the wrong repo so i pushed it here again (had this link in the requirements already) 

MicroShop is a local-development microservices demo showing event-driven order processing and observability.

Overview
- A small multi-service system using FastAPI services, a React (Vite) frontend, RabbitMQ for events, and Postgres databases.

Core services
- `product-service` — product catalog and CRUD.
- `cart-service` — user carts.
- `order-service` — creates orders, persists them, and publishes `OrderPlaced` events.
- `payment-service` — simulates payments and updates order status via internal API.
- `order-consumer` — consumes `OrderPlaced` events and drives payments with retry/backoff.
- `auth-service` — issues tokens used by frontend and services.
- `gateway` — API proxy and entrypoint for the frontend.
- `log-service` — centralized JSON log persistence in Postgres.

Quick start (development)
1. Install Docker & Docker Compose.
2. Create an `.env`
3. Start the full stack:

```bash
docker-compose up -d --build
```

4. Frontend & API
- API gateway: http://localhost:8000
- To run frontend with HMR (optional):

```bash
cd frontend
npm install
npm run dev
```

Key behaviors
- Order creation: frontend calls `POST /orders` → `order-service` stores order (status `PENDING_PAYMENT`) and publishes `OrderPlaced`.
- Payment processing: `order-consumer` consumes events and calls `payment-service`. The consumer retries transient errors and marks orders `PAID` or `PAYMENT_FAILED`.
- The frontend polls `GET /orders/{id}` to show final status and offers a manual retry button for users.

Configuration
- `docker-compose.yml` contains most per-service env vars. Notable variables:
	- `PAYMENT_SUCCESS_RATE` — floats 0.0–1.0 to simulate flaky payments.
	- `ORDER_CONSUMER_RETRY_ATTEMPTS`, `ORDER_CONSUMER_BACKOFF_INITIAL`, `ORDER_CONSUMER_BACKOFF_MULTIPLIER` — consumer retry policy.
	- `INTERNAL_API_KEY` — shared key for internal endpoints (order-service internal read/patch).

Reset & seed
- Use `scripts/reset_and_seed.py` to truncate `product` and `order` tables and insert example products.
- Recommended: run it from a temporary Python container connected to the compose network so it can reach the `db` host. Example (Windows PowerShell):

```powershell
# ensure DB is running
docker-compose up -d db

docker run --rm --network likeyeahidk_default -v "%cd%":/work -w /work -e POSTGRES_USER=%POSTGRES_USER% -e POSTGRES_PASSWORD=%POSTGRES_PASSWORD% python:3.11-slim bash -c "pip install psycopg2-binary && python scripts/reset_and_seed.py --host db --port 5432 --user $POSTGRES_USER --password $POSTGRES_PASSWORD --product-db ${PRODUCT_DB:-product_db} --order-db ${ORDER_DB:-order_db} --yes"
```

Observability & debugging
- Each service exposes `/metrics` for Prometheus. Prometheus is available at `http://localhost:9090` when compose is running.
- Use `/demo/logs` endpoints on services to emit demo WARN/ERROR messages to the central `log-service`.
- `order-service` exposes `/internal/debug/routes` to help troubleshoot internal routing.

Files to inspect
- `frontend/src` — React UI and polling/retry UX.
- `order-service/main.py` — order lifecycle and event publishing.
- `order-consumer/main.py` — consumer retry logic and payment orchestration.
- `payment-service/main.py` — payment simulation and idempotent updates.

