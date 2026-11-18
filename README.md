# guestbook-compose-demo

A small, runnable Docker Compose project for learning (or interview prep on)
the core Compose/Docker concepts: **multi-container communication**,
**network isolation**, **named volumes**, and **healthchecks**.

It's a classic 3-tier "guestbook" app: a static frontend behind nginx, a
Flask REST API, a Postgres database, and a Redis cache — plus an optional
Adminer UI gated behind a Compose *profile*.

---

## 1. Architecture

```
                         HOST MACHINE
              (localhost:8080)   (localhost:8081, only with --profile debug)
                     |                         |
                     v                         v
          +----------------------+   +--------------------+
          |       nginx          |   |      adminer       |
          |  (reverse proxy +    |   |   (debug profile)  |
          |   static frontend)   |   +--------------------+
          +----------------------+             |
                     |                         |
       ======== frontend-net ========          |
                     |                         |
          +----------------------+             |
          |         api          |             |
          |  (Flask REST API)    |             |
          +----------------------+             |
                     |                         |
       ======== backend-net =========================
                     |                         |      |
          +----------------------+   +--------------------+
          |          db          |   |        cache        |
          |   (Postgres 16)      |   |   (Redis 7-alpine)  |
          +----------------------+   +--------------------+
```

**Who is on which network:**

| Service   | frontend-net | backend-net | Host port |
|-----------|:------------:|:-----------:|-----------|
| nginx     | yes          | **no**      | 8080      |
| api       | yes          | yes         | (none)    |
| db        | no           | yes         | (none)    |
| cache     | no           | yes         | (none)    |
| adminer   | no           | yes         | 8081 (debug profile only) |

`api` is the **only** service that bridges the two networks. That's
deliberate: it models a real architecture where your edge/proxy tier should
never have a direct path to your data tier — all data access must go
through the application layer.

### Why nginx literally *cannot* reach db or cache

Docker Compose creates one isolated bridge network per `networks:` entry,
and each service's embedded DNS entry (its service name, e.g. `db`) is only
registered on the networks that service is attached to. Since `nginx` is
attached to `frontend-net` only, there is no DNS record for `db` or `cache`
inside the nginx container, and no routable network path to their IPs
either — they're on a different, separate bridge network entirely. This
isn't an application-level permission check; it's actual L3/L2 network
segmentation, enforced by the Docker daemon. You can prove this yourself in
section 4 below.

### How a request flows end-to-end

1. Browser on your host loads `http://localhost:8080/` → hits `nginx`.
2. `nginx` serves `index.html` / `app.js` directly from its own filesystem
   (no proxying needed for static assets).
3. The page's JS calls `fetch("/api/messages")` (a *relative* URL, so it's
   still going to `localhost:8080`).
4. `nginx`'s `location /api/ { proxy_pass http://api:5000/; }` rule rewrites
   that request and forwards it to the `api` service. The hostname `api`
   resolves via Docker's embedded DNS because nginx and api share
   `frontend-net`.
5. Flask's `/messages` handler opens a connection to Postgres using the
   hostname `db` (resolved via embedded DNS on `backend-net`), runs a query,
   and returns JSON.
6. `/visits` does the same thing against Redis using hostname `cache`.

---

## 2. Project layout

```
guestbook-compose-demo/
├─ docker-compose.yml
├─ .env                      # POSTGRES_DB / USER / PASSWORD (demo creds)
├─ .dockerignore
├─ README.md
├─ api/
│  ├─ Dockerfile
│  ├─ requirements.txt
│  ├─ app.py
│  └─ .dockerignore
└─ nginx/
   ├─ Dockerfile
   ├─ nginx.conf
   └─ html/
      ├─ index.html
      └─ app.js
```

---

## 3. Running it

Prerequisite: Docker Desktop / Docker Engine with Compose v2 (the
`docker compose` subcommand, not the old standalone `docker-compose`).

```bash
cd guestbook-compose-demo

# Build images and start the core 4 services (nginx, api, db, cache).
docker compose up -d --build

# Check container + healthcheck status.
docker compose ps
# db and cache should show "healthy" once their healthchecks pass;
# api only starts after both report healthy (depends_on condition).

# Tail the API logs — useful to watch the retry-on-connect logic and
# confirm the `messages` table got created.
docker compose logs -f api
```

Then open **http://localhost:8080** in a browser. You should see the
visit counter increment on each reload, and be able to submit a
name + message and see it appear in the list.

Quick API smoke test with curl (still goes through nginx on 8080, not
directly to the api container, since api has no published port):

```bash
curl http://localhost:8080/api/visits
curl http://localhost:8080/api/messages
curl -X POST http://localhost:8080/api/messages \
     -H "Content-Type: application/json" \
     -d '{"name": "Ada", "message": "Compose networking makes sense now!"}'
```

---

## 4. Proving network isolation (the interview-ready demo)

This is the core exercise: show that `nginx` cannot reach `db`, while `api`
can.

**From inside nginx (attached only to frontend-net):**

```bash
docker compose exec nginx sh
# inside the container:
getent hosts db      # -> no output / resolution failure (no DNS record)
ping -c 2 db         # -> "bad address 'db'" or similar resolution failure
getent hosts api     # -> works! nginx and api share frontend-net
exit
```

**From inside api (attached to both networks):**

```bash
docker compose exec api sh
# inside the container:
getent hosts db      # -> resolves to db's container IP on backend-net
getent hosts cache   # -> resolves to cache's container IP on backend-net
exit
```

The nginx image is `nginx:alpine`, which doesn't ship a full `ping`/`ip`
toolkit by default in some variants — if `ping` isn't available, `getent
hosts db` returning nothing (vs. a real IP for `getent hosts api`) is
already the proof: no DNS record exists for a service nginx has no network
path to.

You can also inspect the networks directly from the host:

```bash
docker network inspect guestbook-compose-demo_frontend-net
docker network inspect guestbook-compose-demo_backend-net
```

Look at the `Containers` section of each — `nginx` will only appear under
`frontend-net`, and `db`/`cache` will only appear under `backend-net`. `api`
is the only container listed in both.

---

## 5. Running with Adminer (optional debug profile)

Adminer is defined with `profiles: [debug]`, so it's excluded from a
normal `docker compose up`. Start it explicitly when you want to inspect
the database by hand:

```bash
docker compose --profile debug up -d
```

Then open **http://localhost:8081** and log in with:

- **System:** PostgreSQL
- **Server:** `db`  (the Compose service name — Adminer is on backend-net too)
- **Username:** value of `POSTGRES_USER` in `.env` (`guestbook_user` by default)
- **Password:** value of `POSTGRES_PASSWORD` in `.env` (`guestbook_pass` by default)
- **Database:** value of `POSTGRES_DB` in `.env` (`guestbook` by default)

Note Adminer can reach `db` directly because it's also on `backend-net` —
unlike nginx, it was never meant to be isolated from the data tier; it's a
deliberate, explicit admin backdoor you opt into with `--profile debug`,
not something exposed by default.

---

## 6. Teardown

```bash
# Stop and remove containers + default network, KEEP the dbdata volume
# (Postgres data survives; next `up` resumes with the same data).
docker compose down

# Stop and remove containers AND the named volume (wipes Postgres data
# for a truly clean slate).
docker compose down -v

# If you started with the debug profile, tear that down the same way;
# `down` without --profile still removes profiled services that are
# currently running.
docker compose down -v
```

---

## 7. Key concepts recap (for quick review)

- **Service discovery / embedded DNS:** containers reach each other by
  *service name* (e.g. `db`, `cache`, `api`), never by hardcoded IP.
  Compose registers each container's name on every network it's attached
  to; DNS resolution only succeeds on shared networks.
- **Network isolation:** defining multiple networks and attaching services
  selectively is how you enforce "the proxy tier cannot touch the data
  tier" at the infrastructure level, not just via app-level config.
- **Named volumes:** `dbdata` persists Postgres's data directory across
  `docker compose down` / `up` cycles; only `down -v` destroys it.
- **Healthchecks + `depends_on: condition: service_healthy`:** ensures
  `api` doesn't even start until `db` and `cache` are confirmed ready to
  accept connections, not just "started" (a container can be running
  before its process inside is actually ready).
- **Defense in depth:** `api`'s own retry-on-connect loop in `app.py`
  is a second safety net beyond the healthcheck-gated startup order —
  good practice for any service that depends on another over a network.
- **Compose profiles:** `profiles: [debug]` lets you ship an optional
  service (here, Adminer) in the same compose file without it running by
  default, keeping the "production-like" default footprint minimal.
