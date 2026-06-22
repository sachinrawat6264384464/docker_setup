FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Collect static files (with a dummy secret key just for the build step)
RUN SECRET_KEY=dummy-key-for-build python manage.py collectstatic --noinput || true

EXPOSE 8000

CMD ["sh", "-c", "python wait_for_db.py && python manage.py migrate_schemas --shared --noinput && python manage.py seed_demo_data && exec gunicorn propflow.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120"]

