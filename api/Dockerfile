# Small, slim Python base image.
FROM python:3.12-slim

# Avoid writing .pyc files and buffer stdout/stderr (useful for
# `docker compose logs -f api`).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first so Docker can cache this layer when only
# app.py changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Create and switch to a non-root user — a basic container security
# practice worth knowing for interviews.
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

EXPOSE 5000

# gunicorn is a production-grade WSGI server; 2 workers is plenty for a
# demo app. flask's own dev server (`flask run`) is single-threaded and
# not meant for anything beyond local debugging.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "app:app"]
