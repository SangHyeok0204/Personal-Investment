# Build context is the repository root (see docker-compose api service).
FROM python:3.12-slim

WORKDIR /app

COPY apps/api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY apps/api/ /app/
COPY database/ /app/database/
COPY alembic.ini /app/alembic.ini

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
