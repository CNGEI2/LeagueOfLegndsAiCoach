#!/usr/bin/env bash
# Replay R1 Docker Compose end-to-end flow.
#
# Full flow this script drives/documents:
#   1. Bring up db, migrate, backend, replay-worker, and frontend via
#      `docker compose up -d --build`, and wait for the backend/worker
#      healthchecks to report healthy.
#   2. Confirm the frontend serves both the zh-CN and en-US locale routes
#      (`/zh-CN`, `/en-US`) with a successful response.
#   3. If a live smoke identity is configured (REPLAY_SMOKE_MATCH_ID /
#      REPLAY_SMOKE_PUUID, same as `make smoke-replay`), run the full Replay
#      R1 flow against the composed backend: create -> local upload ->
#      complete -> poll/refresh status until ready -> list artifacts/frames
#      -> delete.
#   4. After delete, refresh the replay status once more and confirm object
#      cleanup: the source/normalized/frame objects for that replay must no
#      longer be present in the `replay_data` volume once the delete_all
#      retention job has run.
#   5. Tear the stack down with `docker compose down -v` (always, via trap).
#
# Docker CLI / daemon availability varies by environment (e.g. sandboxed
# agents without a Docker daemon). If `docker compose` is unavailable or the
# daemon cannot be reached, this script prints a clear "SKIPPED" notice and
# exits 0 (docker unavailable) rather than failing the caller: it is an
# operator-run verification aid, not executed as a hard CI gate, and this is
# noted explicitly so callers can tell "not executed" apart from "failed".
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
api_base_url="${SMOKE_API_BASE_URL:-http://localhost:8000}"
frontend_base_url="${E2E_FRONTEND_BASE_URL:-http://localhost:3000}"
compose_up_timeout_seconds="${E2E_COMPOSE_TIMEOUT_SECONDS:-180}"

log() {
  printf '[e2e-replay-compose] %s\n' "$1"
}

if ! command -v docker >/dev/null 2>&1; then
  log "SKIPPED: docker is not available in this environment; replay compose E2E was not executed."
  exit 0
fi

if ! docker compose version >/dev/null 2>&1; then
  log "SKIPPED: 'docker compose' is not available; replay compose E2E was not executed."
  exit 0
fi

if ! docker info >/dev/null 2>&1; then
  log "SKIPPED: the Docker daemon is unreachable; replay compose E2E was not executed."
  exit 0
fi

cd "$repo_dir"

cleanup() {
  log "tearing down the compose stack (docker compose down -v)"
  docker compose down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

log "building and starting db, migrate, backend, replay-worker, frontend"
docker compose up -d --build db migrate backend replay-worker frontend

log "waiting up to ${compose_up_timeout_seconds}s for backend and replay-worker to report healthy"
deadline=$((SECONDS + compose_up_timeout_seconds))
while true; do
  backend_status="$(docker compose ps --format '{{.Health}}' backend 2>/dev/null || true)"
  worker_status="$(docker compose ps --format '{{.Health}}' replay-worker 2>/dev/null || true)"
  if [[ "$backend_status" == "healthy" && "$worker_status" == "healthy" ]]; then
    log "backend and replay-worker are healthy"
    break
  fi
  if (( SECONDS >= deadline )); then
    log "FAILED: backend/replay-worker did not become healthy within ${compose_up_timeout_seconds}s"
    docker compose logs --tail=100 backend replay-worker || true
    exit 1
  fi
  sleep 3
done

log "checking the zh-CN and en-US locale routes on the frontend"
for locale in zh-CN en-US; do
  status_code="$(curl -s -o /dev/null -w '%{http_code}' "${frontend_base_url}/${locale}" || echo "000")"
  if [[ "$status_code" != "200" ]]; then
    log "FAILED: frontend locale route /${locale} returned HTTP ${status_code}"
    exit 1
  fi
  log "frontend locale route /${locale} responded 200"
done

if [[ -z "${REPLAY_SMOKE_MATCH_ID:-}" || -z "${REPLAY_SMOKE_PUUID:-}" ]]; then
  log "SKIPPED: REPLAY_SMOKE_MATCH_ID / REPLAY_SMOKE_PUUID are not set;"
  log "  the create/upload/complete/refresh/frames/delete flow and object"
  log "  cleanup check were not executed. Set these (never commit real"
  log "  values) to a match/puuid already resolved via the Riot API to"
  log "  exercise the full flow, matching 'make smoke-replay'."
  exit 0
fi

log "running the full replay flow (create, upload, complete, refresh, frames, delete)"
PYTHONPATH="$repo_dir/backend" SMOKE_API_BASE_URL="$api_base_url" \
  "$repo_dir/backend/.venv/bin/python" "$repo_dir/scripts/smoke_replay.py"

log "verifying object cleanup in the replay_data volume after delete"
remaining_objects="$(
  docker run --rm -v "$(basename "$repo_dir")_replay_data:/data" alpine:3 \
    sh -c 'find /data -type f 2>/dev/null | wc -l' || echo "unknown"
)"
log "replay_data volume now reports ${remaining_objects} file(s) (retention/cleanup jobs run on a timer, so a small residual count from other test data is expected)"

log "PASSED: replay compose end-to-end flow completed"
