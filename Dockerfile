# The API and the Celery worker ship in this one image.
#
# They run as separate containers with different commands, but they import the
# same code and need the same dependencies, so keeping two images would only
# create two things to keep in sync.
#
# Two stages: the first one installs, the second one only receives the finished
# virtualenv and the source. Nothing that was needed to build - uv, compilers,
# caches - reaches the image that runs in production.

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

# Bytecode is compiled at build time so the first request does not pay for it,
# and copy mode avoids hardlinks that would not survive the stage boundary.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first, in their own layer: they change far less often than the
# code, so editing a router does not reinstall the world.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend ./backend
RUN uv sync --frozen --no-dev


FROM python:3.12-slim

# A process that does not need root should not have it: if anything ever
# executes inside this container, it executes as nobody in particular.
RUN useradd --create-home --uid 1000 app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY backend ./backend
COPY alembic.ini ./

# Uploaded manuals land here. In compose this path is a volume shared with the
# worker, which reads the PDF the API wrote.
RUN mkdir -p /app/uploads && chown app:app /app/uploads

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app

EXPOSE 8000

CMD ["uvicorn", "nomanual.main:app", "--host", "0.0.0.0", "--port", "8000"]
