FROM python:3.11-slim

# Unbuffered stdout/stderr — otherwise uvicorn's logs can sit in a Python
# buffer instead of reaching `docker logs`/Azure's log stream promptly.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies in their own layer, before the rest of the source — so an
# app-code-only change doesn't invalidate the (slow) pip install layer on
# every rebuild.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# See .dockerignore — without it this COPY would bake backend/.env's real
# secrets into the image. Verify it's actually being respected, not just
# present: `docker build` should never show .env in its context.

# Runs as an unprivileged user rather than the default root — standard
# hardening for a container that's actually going to be deployed, not just
# run locally for a demo.
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

EXPOSE 8000

# Alembic migrations are NOT run here — deliberately. Baking `alembic
# upgrade head` into CMD means every container start (every replica, every
# restart) races to run migrations concurrently, which is exactly the kind
# of thing that corrupts a schema under real deployment. Run it as its own
# one-off step (a GitHub Actions job, an Azure deployment task, or by hand)
# before traffic hits a new revision — see SKILL.md's local-dev equivalent.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/docs', timeout=3)" || exit 1

# `python -m uvicorn`, not the bare `uvicorn` console-script — this exact
# distinction is what broke the real Azure App Service deploy (Aug 2026):
# Oryx's build extracts the app into a virtualenv where the `uvicorn`
# executable's own sys.path[0] insertion doesn't include the app directory,
# so `import api` fails with ModuleNotFoundError even though the app is
# right there. `python -m` explicitly adds the current working directory to
# sys.path, which fixes it. The bare `uvicorn` CMD this replaced had already
# verified working in a local `docker build && docker run` test in this same
# image — Docker's plain venv-less install doesn't hit the same failure —
# so this wasn't a proven bug here, just made consistent with the one
# environment where it demonstrably was one, since there's no downside.
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
