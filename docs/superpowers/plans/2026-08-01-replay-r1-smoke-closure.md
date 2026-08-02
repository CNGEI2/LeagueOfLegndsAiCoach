# Replay R1 Real Smoke Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the real Docker Compose replay lifecycle `create -> upload -> process -> delete -> zero residual objects` pass with the actual NA match and Riot API, while keeping the smoke test faithful to production deletion semantics.

**Architecture:** Keep the existing replay API, worker, S3/MinIO storage, and Compose harness unchanged. Fix the FFmpeg normalization contract at the command builder so every accepted upload produces an explicit 30 FPS output. Teach the smoke client that an authenticated `404 REPLAY_NOT_FOUND` after deletion is the expected terminal state because deletion scrubs the access-token digest. Continue using the Compose volume inspection as the independent proof that storage is empty.

**Tech Stack:** Python 3.12, FastAPI, httpx, pytest, FFmpeg/ffprobe, PostgreSQL, MinIO, Docker Compose, shell contract tests.

## Global Constraints

- Start from branch `feature/replay-r1` after commit `d9082cc`.
- Do not revert or rewrite `d9082cc`; it contains the match prewarm, smoke platform setting, and zero-object assertion.
- Never print or commit `RIOT_API_KEY`, `OPENAI_API_KEY`, PUUID, replay access tokens, upload URLs, or the contents of `.env`.
- Run the real smoke only with environment variables exported from the local `.env`; `.env` remains ignored.
- A generic 404 must not count as successful deletion. Only the structured error code `REPLAY_NOT_FOUND` is accepted.
- Do not weaken media validation or change the supported upload contract to work around FFmpeg behavior.
- Follow red-green-refactor for every code change and commit only after the focused tests pass.

---

## Task 1: Make normalized output explicitly 30 FPS

**Files:**

- Modify: `backend/tests/test_replay_media.py`
- Modify: `backend/app/services/replays/media.py`
- Modify: `backend/tests/integration/test_replay_ffmpeg.py`

- [ ] **Step 1: Add a failing unit contract for the output frame rate**

Extend `test_normalize_command_includes_required_flags` so it requires a distinct output `-r 30` argument after `-fps_mode cfr` and before the output path:

```python
fps_mode_index = command.index("-fps_mode")
output_rate_index = command.index("-r")

assert command[fps_mode_index + 1] == "cfr"
assert command[output_rate_index + 1] == "30"
assert fps_mode_index < output_rate_index < len(command) - 1
```

This is intentionally separate from checking that the video filter contains `fps=30`: the real container run proved the filter alone can still be muxed as 25 FPS.

- [ ] **Step 2: Verify the new unit test fails for the right reason**

Run:

```bash
cd backend
pytest -q tests/test_replay_media.py::test_normalize_command_includes_required_flags
```

Expected: failure because `"-r"` is not present in the current command.

- [ ] **Step 3: Add the minimal FFmpeg output-rate argument**

In `build_normalize_command`, place the explicit output rate immediately after CFR selection:

```python
"-fps_mode",
"cfr",
"-r",
"30",
"-movflags",
"+faststart",
```

Do not remove `fps=30` from the filter. The filter controls frame generation and `-r 30` makes the output stream/muxer contract explicit.

- [ ] **Step 4: Verify the unit test passes**

Run:

```bash
cd backend
pytest -q tests/test_replay_media.py::test_normalize_command_includes_required_flags
```

Expected: `1 passed`.

- [ ] **Step 5: Strengthen the real FFmpeg integration test**

Change the generated source fixture from `rate=30` to `rate=25`, assert the probed source rate is 25, and require normalization to convert it to exactly 30. Use the existing typed probe fields:

```python
assert probe.video_streams[0].avg_frame_rate == 25.0
...
normalized_video = normalized_probe.video_streams[0]
assert normalized_video.avg_frame_rate == 30.0
assert normalized_video.codec_name == "h264"
assert normalized_video.pix_fmt == "yuv420p"
```

Keep the existing progress assertions, including monotonic progress and the final 80% worker-stage value.

- [ ] **Step 6: Run the real FFmpeg test**

Run the repository's existing real-FFmpeg command, or from `backend`:

```bash
pytest -q -m integration tests/integration/test_replay_ffmpeg.py
```

Expected: `1 passed` and the normalized stream is reported as 30 FPS.

- [ ] **Step 7: Commit the media fix**

```bash
git add backend/app/services/replays/media.py backend/tests/test_replay_media.py backend/tests/integration/test_replay_ffmpeg.py
git commit -m "fix: enforce replay normalization output frame rate"
```

---

## Task 2: Match the smoke test to deletion scrubbing semantics

**Files:**

- Modify: `backend/tests/test_replay_smoke_script.py`
- Modify: `scripts/smoke_replay.py`

- [ ] **Step 1: Replace the unrealistic deleted-payload test fixture**

Change the happy-path response sequence so the GET after DELETE returns the real public contract:

```python
FakeResponse(
    {"error": {"code": "REPLAY_NOT_FOUND", "message": "Replay not found"}},
    status_code=404,
)
```

Assert `run_smoke(...)` still completes successfully. If `FakeResponse.raise_for_status()` needs an explicit configured exception, configure it exactly as the existing error-path tests do.

- [ ] **Step 2: Add negative deletion cases before implementation**

Add focused tests proving:

1. `404 REPLAY_NOT_FOUND` after DELETE ends polling successfully.
2. `404 MATCH_NOT_FOUND` after DELETE raises `SmokeFailure("MATCH_NOT_FOUND")`.
3. a non-JSON 404 raises `SmokeFailure("SMOKE_REQUEST_FAILED")`.
4. a readable `status == "deleted"` remains accepted for backward compatibility.

Do not accept all 404 responses.

- [ ] **Step 3: Verify the focused tests fail**

Run:

```bash
cd backend
pytest -q tests/test_replay_smoke_script.py
```

Expected: the new real-deletion case fails because `_request_json` currently rejects the 404 before `_poll_deleted` can classify it.

- [ ] **Step 4: Add a narrow accepted-error path to the request helper**

Extend `_request` with an immutable accepted-code parameter:

```python
def _request(
    client: SmokeClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    content: object | None = None,
    json: object | None = None,
    accepted_error_codes: frozenset[str] = frozenset(),
) -> SmokeResponse:
    ...
```

Before calling `raise_for_status()` for an HTTP error, safely decode the standard error envelope. Return the response unchanged only when its exact error code is in `accepted_error_codes`. Keep all existing transport, JSON, and generic HTTP failures mapped to their current smoke error codes.

Extract the existing dictionary-decoding portion of `_request_json` into:

```python
def _response_mapping(response: SmokeResponse) -> dict[str, object]: ...
```

`_request_json` calls `_request(..., expect_json=True)` and then `_response_mapping(response)`. This keeps response parsing in one place.

- [ ] **Step 5: Use the exception only in deletion polling**

Update `_poll_deleted` to call `_request` directly with:

```python
accepted_error_codes=frozenset({"REPLAY_NOT_FOUND"})
```

Terminate successfully when the returned response has status 404 and `_safe_error_code(response) == "REPLAY_NOT_FOUND"`. For a 200 response, pass the response to `_response_mapping` and retain the existing `deleted`, `failed`, `expired`, and timeout behavior. Return `{"status": "deleted"}` for the accepted scrubbed case so `_poll_deleted` keeps its existing return type.

No other request in the smoke flow may pass an accepted error code.

- [ ] **Step 6: Run the smoke-script unit tests**

Run:

```bash
cd backend
pytest -q tests/test_replay_smoke_script.py tests/test_replay_e2e_compose_contract.py
```

Expected: all focused smoke and Compose contract tests pass.

- [ ] **Step 7: Commit the deletion-contract fix**

```bash
git add scripts/smoke_replay.py backend/tests/test_replay_smoke_script.py
git commit -m "fix: accept scrubbed replay as deleted in smoke test"
```

---

## Task 3: Prove the full real lifecycle and no-residue guarantee

**Files:**

- Verify: `.env`
- Verify: `scripts/e2e_replay_compose.sh`
- Verify: `scripts/smoke_replay.py`
- Verify: `docker-compose.yml`

- [ ] **Step 1: Check required local values without printing secrets**

Confirm these names exist and are non-empty in the local `.env`:

```text
RIOT_API_KEY
REPLAY_SMOKE_PLATFORM=NA1
REPLAY_SMOKE_MATCH_ID
REPLAY_SMOKE_PUUID
```

Use a presence-only check. Never echo values. The player is on North America; server auto-detection is a separate feature and is not a prerequisite for this Replay R1 closure.

- [ ] **Step 2: Run focused backend regression tests**

Run:

```bash
cd backend
pytest -q tests/test_replay_media.py tests/test_replay_smoke_script.py tests/test_replay_e2e_compose_contract.py
```

Expected: all pass.

- [ ] **Step 3: Run the full real Compose lifecycle**

From the repository root, load the ignored `.env` into the process environment and run:

```bash
make e2e-replay-compose
```

The run must not say the real smoke was skipped. Required observed milestones:

1. backend and worker become healthy;
2. match cache prewarm succeeds;
3. replay creation and upload succeed;
4. worker reaches `ready`;
5. DELETE is accepted;
6. polling reaches `REPLAY_NOT_FOUND` or `deleted`;
7. the replay storage volume contains zero files;
8. both `/zh-CN` and `/en-US` return 200.

- [ ] **Step 4: Diagnose failures without weakening assertions**

If the lifecycle fails, capture only service names, status, public error codes, and sanitized logs. Do not log bearer tokens, presigned URLs, PUUID, or API keys. Keep the Compose environment until the failure is understood, then use the script's normal cleanup path.

- [ ] **Step 5: Run the complete verification matrix**

Run the same repository commands used by CI/release validation:

```bash
cd backend
pytest -q
```

Run PostgreSQL, real FFmpeg, and the complete non-integration/frontend checks:

```bash
make verify
make verify-postgres
make verify-replay-postgres
make verify-replay-ffmpeg
```

With the previously configured real MinIO endpoint, require the endpoint and run the two streaming tests explicitly:

```bash
test -n "$REPLAY_S3_TEST_ENDPOINT"
cd backend
.venv/bin/pytest -m replay_s3 tests/integration/test_replay_s3_streaming.py -v
cd ..
```

Finally rerun `make e2e-replay-compose` once after the full suite.

Expected minimums must not regress from the latest accepted baseline:

- backend: at least 370 passed, 1 skipped, plus the new tests;
- PostgreSQL: 14 integration and 23 repository-contract tests, plus any new assertion;
- real FFmpeg: 1 passed;
- real MinIO: 2 passed;
- frontend: 86 tests, lint, typecheck, and production build pass;
- real Compose lifecycle: not skipped and zero storage files after deletion.

- [ ] **Step 6: Record verification evidence in the final handoff**

Report exact commands, pass counts, the real lifecycle result, and whether Compose resources were cleaned. Do not commit generated videos, logs, MinIO objects, `.env`, or secret-bearing output.

---

## Definition of Done

- Normalized replay video probes as exactly 30 FPS in a real FFmpeg test.
- The smoke client treats only `404 REPLAY_NOT_FOUND` as the scrubbed deletion terminal state.
- The real NA replay lifecycle runs from creation through deletion without being skipped.
- The E2E harness independently verifies zero files remain in replay storage.
- All existing backend, PostgreSQL, FFmpeg, MinIO, frontend, and Compose checks pass.
- No secrets or player identifiers are added to git history or test output.
