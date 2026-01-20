FROM python:3.10-slim
WORKDIR /app
COPY main.py .
# install required Python packages (including Postgres client)
RUN pip install --no-cache-dir fastapi uvicorn psycopg2-binary prometheus_client
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
