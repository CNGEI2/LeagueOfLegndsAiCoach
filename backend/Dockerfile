FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
# Non-root runtime user for both the API and the replay worker. A fixed
# numeric UID/GID lets the replay data volume be pre-seeded with the right
# ownership below, and lets docker-compose pin `user:` without an /etc/passwd
# lookup inside the (possibly read-only) container.
RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid appuser --no-create-home --shell /usr/sbin/nologin appuser
COPY pyproject.toml ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN python -m pip install --no-cache-dir . \
    # Docker seeds a named volume from the image's target directory the first
    # time it is mounted, so pre-creating this with the runtime user's
    # ownership here is what makes `/var/lib/lol-ai-coach/replays` writable
    # by a non-root, read-only-root-filesystem worker container.
    && mkdir -p /var/lib/lol-ai-coach/replays \
    && chown -R appuser:appuser /app /var/lib/lol-ai-coach/replays
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
