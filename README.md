# Spill

A prompt-driven tabletop harness for Karma's bimanual YAM, an overhead D435,
and two wrist D405 cameras. Astra plans and checks progress; Dream predicts
joint trajectories; Karma retains exclusive motor ownership and native protection.

**Experimental: operator-run hardware trials have exercised APIs, arm motion,
shutdown and recording, but reliable pill transfer has not been established.**
Recurring motor-feedback gaps remain unresolved. Mock mode is a joint echo with
synthetic cameras, not a pouring simulation. Measured scene calibration is optional
only in explicit zero-shot mode, which disables geometric collision checks.

Start with the [operating and troubleshooting guide](docs/operations.md).
The [latest diagnosed trial](docs/rollout-2026-11-06.md) distinguishes a planner
pause from a hardware fault. See [validation](docs/validation.md) for test scope.

## Zero-shot on your YAM

To record a local LeRobot v3 dataset using Karma's writer:

```bash
uv run spill --config config/local.json run \
  "Pour all pills into the empty cup" --hardware --zero-shot --grasp top-down --record
```

Top-down cup grasping is now the default instruction for both Astra and Dream;
`--grasp auto` removes that constraint. It is a policy instruction, not a
geometrically enforced orientation constraint.

Recording includes observations and current commanded targets during motion and
API waits; parking is excluded. Images are archived asynchronously, then Karma's
LeRobot v3 writer packages videos and Parquet **after motor shutdown** in
`runs/<run-id>/lerobot_v3`. No data is uploaded. Outcome and fault metadata live in
`spill_rollout.json`; failed and interrupted episodes are not labeled successful.
Samples are resampled causally to 20 Hz with source timestamps retained; gaps over
200 ms become separate episodes. The dataset uses Karma's convention **0=open,
1=closed**, converted from native state/actions. Existing logs can be converted
with `uv run spill export-v3 runs/<run-id>`; older logs contain command segments
only, so their metadata explicitly identifies that limitation. Existing datasets
are never overwritten.

Motor-feedback faults still stop in place. New fault logs include per-motor
feedback ages and recent telemetry in `observation_fault` events. The bounded
executor permits at most 0.01 rad of initial boundary error to recover gradually
toward the normal joint range; it never permits motion further outside that range.

Every completed run writes `runs/<run-id>/summary.json` alongside `events.jsonl`,
camera observations, raw Dream predictions, bounded accepted trajectories and
commands. The summary compares model latencies, commanded motion time, token usage,
retry events and stop reasons. Summarize an older rollout without hardware/API calls:

```bash
uv run spill report runs/20261106T142341-fd6eaa27
```

Astra requests have a 45-second timeout and up to two transient-error retries
with 2/4-second backoff. Each retry captures fresh observations while the robot
holds; Ctrl+C and the wall-clock task timeout remain active. Authentication errors
do not retry. Configure `planner_timeout_s`, `planner_retries`, and
`planner_retry_delay_s` in local settings. No retry guarantees provider availability.

`config/local.json` on this machine contains your `can_left`/`can_right` mappings
and ASIC camera serials. Spill translates ASIC serials using Karma's resolver.
Supply both keys in your shell, or put them in a local `.env` (never commit keys).

```bash
cd /home/yambox/karma/spill
uv sync --locked --project dream_runtime
uv run --env-file .env spill --config config/local.json run \
  "Pour all pills into the empty cup" --hardware --zero-shot
```

The `.env` contains `OPENAI_API_KEY=...` and `DREAM_API_KEY=...`. If the keys are
already exported, omit `--env-file .env`. No calibration file, verification flags,
demonstrations or fine-tuning are required. Astra plans and observes progress;
Dream-1 predicts actions; Karma controls the arms. Authenticated Dream model
availability is still checked. API access and task success are not guaranteed.

Zero-shot skips scene geometry checks (table, obstacles, self/inter-arm collision).
Joint limits, speed/acceleration limits, gripper limits, tracking checks, freshness,
temperature, native Karma protection and stop controls remain active. Viser at
`http://192.168.0.184:8080` on this cell shows cameras, subtasks and trajectories.
The server binds `0.0.0.0`; use `http://<robot-host-ip>:8080` on another cell.
Base placement is
nominal and is labeled as uncalibrated. Ctrl+C requests home then shutdown; a
second interrupt cancels parking. Sustained feedback faults stop in place.
Brief feedback gaps inhibit new commands and invalidate pending predictions;
fresh feedback triggers replanning. Ctrl+C during a gap skips homing.
Keep the home path clear.

For an optional read-only check, use
`uv run spill --config config/local.json doctor --zero-shot --cameras`.
For model preview with energized arms holding position, use `--shadow --zero-shot
--no-park` instead of `--hardware --zero-shot`.

## Run the complete offline demo

```bash
cd /home/yambox/karma/spill
uv sync --locked
uv sync --locked --project dream_runtime
uv run spill run "Pour all pills from the source cup into the empty cup"
```

This starts **mock mode** without API calls or motor access. Open the printed
Viser URL (normally `http://127.0.0.1:8080`). The demo exits after exercising the
pipeline and reports `unverified`, not a fabricated manipulation success.

```bash
uv run spill run "Exercise the harness" --no-viz
uv run pytest -q
uv run ruff check src tests
```

Python 3.12 and dependencies are managed by uv. Karma is an editable dependency
at `..`; do not move Spill away from that checkout without updating the path.
All relative configuration/artifact paths resolve from the current directory;
run these commands from `spill/`.

## Configure calibrated geometric checks (optional)

This section applies when running without `--zero-shot`. The zero-shot path above
does not require a measured calibration file or its verification flags.

```bash
uv run spill init
uv run spill --config config/local.json calibrate
```

Edit `config/local.json` with the real CAN interfaces and camera serials.
`config/calibration.json` is an **unverified template**, not a physical calibration.
Follow [commissioning](docs/commissioning.md) before setting verification flags.
The supplied `config/*.example.json` files are never used as measured values.

Set `OPENAI_API_KEY` and `DREAM_API_KEY` in your shell, or use Dream's supported
credentials file for its key. `.env.example` documents names; files are not
silently sourced. Never commit keys. Astra's default model is `gpt-6-astra`.
Dream's checkpoint is explicit: check the IDs available to your account rather
than silently swapping `dreamlabs/dream-1` and `dreamlabs/dream-1-beta`.

```bash
uv run spill --config config/local.json doctor --cameras --models
uv run spill --config config/local.json calibrate --check
uv run spill --config config/local.json run "Pick up the empty cup" --shadow --no-park
uv run spill --config config/local.json run \
  "Pour every pill from the source cup into the empty cup, then put both cups upright" --hardware
```

**Shadow mode energizes and holds the arms.** It calls models and validates
trajectories but does not execute their motion. Normal shutdown still parks unless
`--no-park` is selected. To avoid energizing anything use the default mock mode,
`doctor`, or `replay` instead.

The default YAM profile adds hand poses with `ik={"arm":"yam","head":"joint"}`
while retaining the model's native joint actions. Dream's full SDK runs in its own
locked environment to avoid a Click/LeRobot dependency conflict:

```bash
uv sync --locked --project dream_runtime
```

`config/dream-yam-pose.example.json` shows this profile. Its SDK worker communicates
over local pipes and never opens hardware. For an explicitly verified checkpoint
that needs only joint observations, `config/dream-joint-only.example.json` uses
the lightweight client directly. Spill never starts Dream's robot station or a
second CAN driver.

## Operator controls

| Control | Behavior |
|---|---|
| Ctrl+C / Home & Stop | Cancel model execution; invoke Karma's native home-and-shutdown path for both arms |
| Second Ctrl+C during parking | Interrupt remaining parking; de-energize in place |
| Stop Now | De-energize without parking; software control, not the physical e-stop |
| Pause / Hold | Invalidate predicted actions; hold measured joints with the last commanded gripper opening |
| Resume | Fresh observations and replanning; old chunks cannot resume |
| `--no-park` | Shutdown without a home move |

The viewer stays active during parking. A park failure does not skip cleanup of
the other arm. Faults involving stale hardware/camera feedback stop in place.
See the complete [Karma safety parity matrix](docs/safety.md).

Access the original Karma CLI in the same environment:

```bash
uv run spill karma doctor --rig yam_bimanual
uv run spill karma cameras --rig yam_bimanual --probe
uv run spill karma teleop --help
```

These are foreground **operator** commands. They are not tools available to Astra.
Never run another robot controller beside an active Spill hardware run.

## Viser

- Live measured arms, predicted endpoint ghosts, and left/right end-effector trails.
- Model trails and accepted trajectories; rejected trajectory diagnostics in logs.
- Progress markers, horizon length, observation age, and model timing.
- Three live cameras and separate Astra/Dream input panels.
- Original prompt, subtask list, active instruction, explanations and evidence.
- Measured/commanded gripper openings and pause/resume/shutdown controls.

Viser binds to localhost. Use SSH port forwarding for a remote operator:
`ssh -L 8080:localhost:8080 robot-host`. Browser loss does not stop the local
supervisor. Rendering uses a separate thread and never opens motor or camera devices.
The gripper mesh is static in Karma's model; numeric opening readouts are authoritative.

## Recording and evaluation

Each run writes `runs/<id>/events.jsonl` and observation arrays. Logs include
configuration, calibration, decisions, Dream timings, rejected/accepted chunks,
commands, and shutdown outcome. Observation archives use full-resolution JPEG95
for bounded disk/CPU cost; exact encoded API image inputs are recorded separately. No API keys are written by Spill. The official
Dream SDK may also transmit its own observation recordings to Dream's service;
this is SDK behavior in addition to inference, not a Spill live-view connection.

```bash
uv run spill replay RUN_ID
uv run spill replay RUN_ID --no-viz
uv run spill evaluate --suite cup-transfer --write-scenes config/cup-scenes.json
uv run spill label RUN_ID --initial 10 --target 10 --residue 0 --spilled 0 --upright
uv run spill evaluate --suite cup-transfer
```

Counts come from an independent human inspection. Occluded/tiny pills are not
assumed to be counted correctly by an image model. Mock and shadow runs never
contribute to the real success rate. Compare `--dream-only` against the normal
Astra+Dream mode using the same 20 scene placements. The target of 18/20 successful
trials is an acceptance goal, not a measured result.

`uv run spill export RUN_ID --output data/pouring-v1` exports uniformly sampled,
independently labeled real command/observation segments to LeRobot v2.1 with
right-first Dream ordering. Uniform 20 Hz recordings are explicitly downsampled
to the service-supported 10 Hz, keeping real aligned rows. Episodes must span
at least 1.6 seconds. It refuses nonuniform timing rather than hiding cloud
holds as a fabricated fixed-rate trajectory. Use `--include-failures` only when
intentionally preparing failure data. Collect corrective demonstrations with
Karma teleop; Karma's v3 datasets require an explicit v2.1 conversion for the
Dream service (do not relabel the format version). Upload/fine-tuning is not automatic.

## Design and limits

See [architecture](docs/architecture.md), [commissioning](docs/commissioning.md),
and [sources](docs/research.md). Default inference is synchronous; adaptive
prefetch is opt-in after latency and continuity validation. Model targets are
bounded to joint ranges and approached within motion limits; nonfinite inputs,
expired predictions and infeasible bounded paths are rejected. Calibration-based
capsules protect the modeled static cell; they do not discover new obstacles or
prove mesh-level clearance. General tabletop performance is task-dependent.
