"""
guestbook-compose-demo -- api/app.py

Flask backend for the Guestbook demo.

KEY TEACHING POINT -- SERVICE-NAME DNS RESOLUTION:
    This container never uses an IP address to reach Postgres or Redis.
    Instead it connects to hostnames "db" and "cache" (see DB_HOST /
    REDIS_HOST below). Those names resolve because Docker Compose creates
    an embedded DNS server on every user-defined bridge network, and
    registers each container under its *service name*. Since this `api`
    service is attached to `backend-net` (the same network as `db` and
    `cache`), the names just work -- no manual IP wiring required.

    By contrast, `nginx` is NOT on `backend-net`, so from inside the nginx
    container `getent hosts db` fails to resolve at all. That is the
    network-isolation proof this whole project is built around.

KEY TEACHING POINT -- STARTUP ORDERING:
    docker-compose.yml already makes `api` wait for `db` and `cache` to
    report healthy (depends_on + condition: service_healthy) before `api`
    is even started. The retry loop below is a *second, defense-in-depth*
    layer: healthchecks prove the process is accepting connections, but
    there is always a small window (cold start, slow disk, etc.) where a
    connection attempt can still race a split second too early. Production
    code should always retry on connect for exactly this reason.
"""

import os
import time

import psycopg2
import redis
from flask import Flask, jsonify, request

app = Flask(__name__)

# --- Configuration from environment variables (set in docker-compose.yml) --
# DB_HOST / REDIS_HOST are Docker Compose *service names*, resolved via
# Docker's embedded DNS -- not hardcoded IPs.
DB_HOST = os.environ.get("DB_HOST", "db")
DB_NAME = os.environ.get("DB_NAME", "guestbook")
DB_USER = os.environ.get("DB_USER", "guestbook_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "guestbook_pass")
DB_PORT = os.environ.get("DB_PORT", "5432")

REDIS_HOST = os.environ.get("REDIS_HOST", "cache")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))


def get_db_connection(retries=10, delay=2):
    """
    Open a new Postgres connection, retrying a few times if the database
    is not ready yet. Each API request opens a short-lived connection,
    which is simple and fine for a demo (a real app would use a
    connection pool, e.g. psycopg2.pool or SQLAlchemy).
    """
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                connect_timeout=5,
            )
            return conn
        except psycopg2.OperationalError as exc:
            last_error = exc
            print(f"[api] DB connection attempt {attempt}/{retries} failed: {exc}")
            time.sleep(delay)
    raise last_error


def get_redis_client():
    """Create a Redis client. redis-py connects lazily, so this never
    raises until the first command is actually sent."""
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def init_db():
    """
    Create the `messages` table if it does not already exist. Called once
    at process startup. Uses the same retry-aware connection helper since
    `db` may still be finishing initialization even though its healthcheck
    has started passing (pg_isready can report ready a moment before the
    server fully accepts every query type, especially on first boot).
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
        conn.commit()
        print("[api] messages table ready")
    finally:
        conn.close()


# Run table bootstrap at import time, so it happens once per gunicorn
# worker process start (and once in `flask run` dev mode too).
init_db()


@app.route("/health")
def health():
    """Simple liveness endpoint. Compose healthchecks for `api` itself are
    not defined in this demo, but this is the natural place to add one
    (e.g. CMD curl -f http://localhost:5000/health)."""
    return jsonify(status="ok"), 200


@app.route("/messages", methods=["GET"])
def list_messages():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, message, created_at FROM messages "
                "ORDER BY created_at DESC;"
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    messages = [
        {
            "id": row[0],
            "name": row[1],
            "message": row[2],
            "created_at": row[3].isoformat(),
        }
        for row in rows
    ]
    return jsonify(messages)


@app.route("/messages", methods=["POST"])
def add_message():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    message = (data.get("message") or "").strip()

    if not name or not message:
        return jsonify(error="both 'name' and 'message' are required"), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO messages (name, message) VALUES (%s, %s) "
                "RETURNING id, name, message, created_at;",
                (name, message),
            )
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()

    return (
        jsonify(
            {
                "id": row[0],
                "name": row[1],
                "message": row[2],
                "created_at": row[3].isoformat(),
            }
        ),
        201,
    )


@app.route("/visits", methods=["GET"])
def visits():
    """Increment and return the Redis-backed page-view counter. INCR is
    atomic, so concurrent requests from multiple gunicorn workers /
    browser tabs never race each other."""
    r = get_redis_client()
    count = r.incr("visit_count")
    return jsonify(visits=count)


if __name__ == "__main__":
    # Only used for local debugging outside Docker; the container runs
    # gunicorn instead (see Dockerfile CMD).
    app.run(host="0.0.0.0", port=5000)
