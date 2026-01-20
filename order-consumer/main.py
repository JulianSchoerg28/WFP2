import os
import json
import time
import pika
import requests
import logging

logger = logging.getLogger("order-consumer")

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/%2F")
LOG_SERVICE = os.getenv("LOG_SERVICE_URL", "http://log-service:8000")
ORDER_SERVICE = os.getenv("ORDER_SERVICE_URL", "http://order-service:8003")
PAYMENT_SERVICE = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8000")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
# retry configuration (env vars allow tuning)
try:
    RETRY_ATTEMPTS = int(os.getenv("ORDER_CONSUMER_RETRY_ATTEMPTS", "3"))
except Exception:
    RETRY_ATTEMPTS = 3
try:
    RETRY_BACKOFF_INITIAL = float(os.getenv("ORDER_CONSUMER_BACKOFF_INITIAL", "3.0"))
except Exception:
    RETRY_BACKOFF_INITIAL = 2.0
try:
    RETRY_BACKOFF_MULTIPLIER = float(os.getenv("ORDER_CONSUMER_BACKOFF_MULTIPLIER", "2.0"))
except Exception:
    RETRY_BACKOFF_MULTIPLIER = 2.0


def safe_log(payload: dict):
    try:
        requests.post(f"{LOG_SERVICE}/logs", json=payload, timeout=2.0)
    except Exception as e:
        logger.warning("safe_log failed: %s", e)


def main():
    params = pika.URLParameters(RABBITMQ_URL)
    while True:
        try:
            conn = pika.BlockingConnection(params)
            ch = conn.channel()
            ch.exchange_declare(exchange="events", exchange_type="topic", durable=True)
            q = ch.queue_declare(queue="order_events_queue", durable=True)
            ch.queue_bind(exchange="events", queue="order_events_queue", routing_key="order.placed")

            logger.info("[consumer] waiting for messages on order_events_queue (order.placed)")

            def callback(ch, method, properties, body):
                try:
                    msg = json.loads(body)
                except Exception:
                    msg = body.decode(errors="replace")
                logger.info("[consumer] received routing_key=%s body=%s", method.routing_key, json.dumps(msg))
                # also send to log-service (best-effort)
                safe_log({"service": "order-consumer", "event": "order_received", "payload": msg})

                # extract order id from message
                order_id = None
                try:
                    if isinstance(msg, dict):
                        if isinstance(msg.get("order"), dict):
                            order_id = msg.get("order").get("id")
                        elif isinstance(msg.get("order"), int):
                            order_id = msg.get("order")
                        elif msg.get("order_id"):
                            order_id = msg.get("order_id")
                        elif msg.get("order", {}).get("order"):
                            order_id = msg.get("order", {}).get("order", {}).get("id")
                except Exception:
                    order_id = None

                if not order_id:
                    logger.warning("[consumer] no order id found in message, acking")
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    return

                # try to process payment via payment-service with retries
                attempts = RETRY_ATTEMPTS
                backoff = RETRY_BACKOFF_INITIAL
                payment_url = f"{PAYMENT_SERVICE}/payment"
                paid = False
                for attempt in range(attempts):
                    try:
                        resp = requests.post(payment_url, json={"order_id": int(order_id)}, timeout=5.0)
                        # Payment service returns result in JSON; require explicit SUCCESS result
                        try:
                            body = resp.json()
                        except Exception:
                            body = {}
                        if resp.status_code == 200 and body.get("result") == "SUCCESS":
                            paid = True
                            logger.info("[consumer] payment succeeded for order %s", order_id)
                            break
                        else:
                            logger.warning("[consumer] payment attempt %s for order %s returned status=%s body=%s", attempt + 1, order_id, resp.status_code, body)
                    except Exception as e:
                        logger.warning("[consumer] payment attempt %s for order %s failed: %s", attempt + 1, order_id, e)
                    time.sleep(backoff)
                    backoff *= 2

                if not paid:
                    # mark order as PAYMENT_FAILED via internal API
                    try:
                        headers = {}
                        if INTERNAL_API_KEY:
                            headers["X-Internal-Key"] = INTERNAL_API_KEY
                        patch_url = f"{ORDER_SERVICE}/orders/{order_id}"
                        requests.patch(patch_url, params={"status": "PAYMENT_FAILED"}, headers=headers, timeout=5.0)
                        logger.warning("[consumer] marked order %s as PAYMENT_FAILED", order_id)
                    except Exception as e:
                        logger.error("[consumer] failed to mark order %s as PAYMENT_FAILED: %s", order_id, e)

                # acknowledge message in all cases
                ch.basic_ack(delivery_tag=method.delivery_tag)

            ch.basic_qos(prefetch_count=1)
            ch.basic_consume(queue="order_events_queue", on_message_callback=callback)
            ch.start_consuming()
        except Exception as e:
            logger.error("[consumer] connection failed: %s, retrying in 3s", e, exc_info=True)
            time.sleep(3)


if __name__ == "__main__":
    main()
