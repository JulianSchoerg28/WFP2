#!/usr/bin/env python3
"""
Reset and seed helper for MicroShop.

Usage:
  PYTHONPATH=. python scripts/reset_and_seed.py --host db --port 5432 --user postgres --password secret --product-db product_db --order-db order_db --yes

The script will TRUNCATE the `product` table in the product DB and the `order` table in the order DB,
then insert a few example products. It requires network access to the Postgres server and
valid credentials. By default it reads connection info from environment variables:
  - POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT
  - PRODUCT_DB, ORDER_DB

Be careful: this will remove data from the specified tables.
"""
import os
import argparse
import psycopg2
from psycopg2 import sql


def connect(dbname, host, port, user, password):
    return psycopg2.connect(dbname=dbname, user=user, password=password, host=host, port=port)


def truncate_tables(conn, tables):
    with conn.cursor() as cur:
        for t in tables:
            cur.execute(sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE;").format(sql.Identifier(t)))
    conn.commit()


def insert_products(conn, products):
    with conn.cursor() as cur:
        for p in products:
            cur.execute(
                "INSERT INTO product (name, description, price) VALUES (%s, %s, %s);",
                (p["name"], p.get("description"), p["price"],),
            )
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("POSTGRES_HOST", "db"))
    parser.add_argument("--port", default=os.getenv("POSTGRES_PORT", "5432"))
    parser.add_argument("--user", default=os.getenv("POSTGRES_USER", "postgres"))
    parser.add_argument("--password", default=os.getenv("POSTGRES_PASSWORD", ""))
    parser.add_argument("--product-db", default=os.getenv("PRODUCT_DB", "product_db"))
    parser.add_argument("--order-db", default=os.getenv("ORDER_DB", "order_db"))
    parser.add_argument("--yes", action="store_true", help="Confirm destructive actions")
    args = parser.parse_args()

    if not args.yes:
        print("This will TRUNCATE tables in the product and order databases. Rerun with --yes to proceed.")
        return

    host = args.host
    port = args.port
    user = args.user
    password = args.password

    print(f"Connecting to product DB '{args.product_db}' on {host}:{port} as {user}")
    try:
        pconn = connect(args.product_db, host, port, user, password)
    except Exception as e:
        print("Failed to connect to product DB:", e)
        return

    print(f"Connecting to order DB '{args.order_db}' on {host}:{port} as {user}")
    try:
        oconn = connect(args.order_db, host, port, user, password)
    except Exception as e:
        print("Failed to connect to order DB:", e)
        pconn.close()
        return

    try:
        print("Truncating product table...")
        truncate_tables(pconn, ["product"])
    except Exception as e:
        print("Failed truncating product table:", e)

    try:
        print('Truncating order table (named "order")...')
        truncate_tables(oconn, ["order"])  # order table is quoted in code
    except Exception as e:
        print("Failed truncating order table:", e)

    products = [
        {"name": "Red T-shirt", "description": "Comfortable red t-shirt", "price": 19.99},
        {"name": "Blue Jeans", "description": "Slim-fit jeans", "price": 49.99},
        {"name": "Coffee Mug", "description": "Ceramic mug 300ml", "price": 9.5},
    ]

    try:
        print("Seeding products...")
        insert_products(pconn, products)
    except Exception as e:
        print("Failed inserting products:", e)

    pconn.close()
    oconn.close()
    print("Done.")


if __name__ == "__main__":
    main()
