# GeoTrack — FastAPI + Alembic image (PostgreSQL via DATABASE_URL)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# copy app sources first so `pip install .` can find the package
COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# runtime deps + postgres driver
RUN pip install --no-cache-dir . psycopg2-binary

EXPOSE 8000

# run migrations, then serve (works on empty Postgres and on existing DBs)
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
