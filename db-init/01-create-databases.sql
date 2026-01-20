SELECT 'CREATE DATABASE product_db' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'product_db')\gexec
SELECT 'CREATE DATABASE auth_db' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'auth_db')\gexec
SELECT 'CREATE DATABASE order_db' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'order_db')\gexec
SELECT 'CREATE DATABASE cart_db' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'cart_db')\gexec
SELECT 'CREATE DATABASE logs_db' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'logs_db')\gexec
