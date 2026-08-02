#!/usr/bin/env bash
# Replay R1 Docker Compose end-to-end flow.
#
# Full flow this script drives/documents:
#   1. Bring up db, migrate, backend, replay-worker, and frontend via
#      `docker compose up -d --build`, and wait for the backend/worker
#      healthchecks to report healthy.
#   2. Confirm the frontend serves both the zh-CN and en-US locale routes
#      (`/zh-CN`, `/en-US`) with a successful response.
#   3. If a live smoke identity is configured (REPLAY_SMOKE_PLATFORM /
#      REPLAY_SMOKE_MATCH_ID / REPLAY_SMOKE_PUUID, same as `make
#      smoke-replay`), run the full Replay R1 flow against the composed
#      backend: load match detail into the fresh DB -> create -> local upload ->
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
# Prefer IPv4 literals so a local process bound only on [::1] cannot steal
# traffic meant for the Compose-published ports.
api_base_url="${SMOKE_API_BASE_URL:-http://127.0.0.1:8000}"
frontend_base_url="${E2E_FRONTEND_BASE_URL:-http://127.0.0.1:3000}"
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

read_smoke_env_value() {
  local name="$1"
  local value="${!name:-}"
  local line
  if [[ -n "$value" ]]; then
    printf '%s' "$value"
    return
  fi
  if [[ ! -f "$repo_dir/.env" ]]; then
    return
  fi
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == "${name}="* ]]; then
      printf '%s' "${line#*=}"
      return
    fi
  done < "$repo_dir/.env"
}

# Compose defaults leave REPLAY_ENABLED=false so the worker refuses to start.
# For this E2E path we force a local, ephemeral replay stack. The token secret
# is generated per run and never written to the repo; operators may override
# via the environment when exercising a longer-lived stack.
export REPLAY_ENABLED=true
export REPLAY_STORAGE_BACKEND="${REPLAY_STORAGE_BACKEND:-local}"
export REPLAY_SMOKE_PLATFORM="$(read_smoke_env_value REPLAY_SMOKE_PLATFORM)"
export REPLAY_SMOKE_PLATFORM="${REPLAY_SMOKE_PLATFORM:-NA1}"
export REPLAY_SMOKE_MATCH_ID="$(read_smoke_env_value REPLAY_SMOKE_MATCH_ID)"
export REPLAY_SMOKE_PUUID="$(read_smoke_env_value REPLAY_SMOKE_PUUID)"
# Settings require >= 32 bytes when replay is enabled.
if [[ -z "${REPLAY_TOKEN_SECRET:-}" || ${#REPLAY_TOKEN_SECRET} -lt 32 ]]; then
  REPLAY_TOKEN_SECRET="e2e-$(openssl rand -hex 32 2>/dev/null || printf '0123456789abcdef0123456789abcdef')-not-for-prod"
  export REPLAY_TOKEN_SECRET
fi

cleanup() {
  log "tearing down the compose stack (docker compose down -v)"
  docker compose down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Prior local runs can leave replay_data objects behind. Wipe compose
# resources first so the post-delete zero-file assertion only measures
# this run's lifecycle, not leftover volume state.
log "resetting any previous compose stack and volumes"
docker compose down -v --remove-orphans >/dev/null 2>&1 || true

log "building and starting db, migrate, backend, replay-worker, frontend (REPLAY_ENABLED=true)"
docker compose up -d --build db migrate backend replay-worker frontend

log "waiting up to ${compose_up_timeout_seconds}s for backend and replay-worker to report healthy"
deadline=$((SECONDS + compose_up_timeout_seconds))
while true; do
  backend_status="$(docker compose ps backend --format '{{.Health}}' 2>/dev/null | tr -d '\r' || true)"
  worker_status="$(docker compose ps replay-worker --format '{{.Health}}' 2>/dev/null | tr -d '\r' || true)"
  if [[ "$backend_status" == "healthy" && "$worker_status" == "healthy" ]]; then
    log "backend and replay-worker are healthy"
    break
  fi
  if (( SECONDS >= deadline )); then
    log "FAILED: backend/replay-worker did not become healthy within ${compose_up_timeout_seconds}s (backend=${backend_status:-unknown} worker=${worker_status:-unknown})"
    docker compose logs --tail=100 backend replay-worker || true
    exit 1
  fi
  sleep 3
done

log "checking the zh-CN and en-US locale routes on the frontend"
frontend_ready_deadline=$((SECONDS + 60))
while true; do
  probe_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${frontend_base_url}/zh-CN" || true)"
  probe_code="${probe_code:-000}"
  if [[ "$probe_code" == "200" ]]; then
    break
  fi
  if (( SECONDS >= frontend_ready_deadline )); then
    log "FAILED: frontend did not respond on ${frontend_base_url} within 60s (last HTTP ${probe_code})"
    docker compose logs --tail=100 frontend || true
    exit 1
  fi
  sleep 2
done
for locale in zh-CN en-US; do
  status_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${frontend_base_url}/${locale}" || true)"
  status_code="${status_code:-000}"
  if [[ "$status_code" != "200" ]]; then
    log "FAILED: frontend locale route /${locale} returned HTTP ${status_code}"
    docker compose logs --tail=50 frontend || true
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

log "verifying zero replay objects in the replay_data volume after delete"
remaining_objects="$(
  docker run --rm -v "$(basename "$repo_dir")_replay_data:/data" alpine:3 \
    sh -c 'find /data -type f 2>/dev/null | wc -l' || echo "unknown"
)"
if ! [[ "$remaining_objects" =~ ^[0-9]+$ ]]; then
  log "FAILED: could not count replay_data volume objects"
  exit 1
fi
if [[ "$remaining_objects" != "0" ]]; then
  log "FAILED: replay_data volume still contains ${remaining_objects} file(s)"
  exit 1
fi
log "replay_data volume contains zero files"

log "PASSED: replay compose end-to-end flow completed"
