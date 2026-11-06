# Operating and diagnosing Spill

Spill is an experimental Astra/Dream controller with Karma as the sole motor
owner. Run it from the `spill/` checkout beside Karma. Do not run another motor
controller on the same CAN interfaces concurrently.

## Start an experiment

Install the locked environments once:

```bash
uv sync --locked
uv sync --locked --project dream_runtime
```

Export `OPENAI_API_KEY` and `DREAM_API_KEY` in the launch terminal, or explicitly
use `uv run --env-file .env ...` with an existing local file. Keys are not stored
in JSON configuration or committed. A new terminal does not inherit exports from
an unrelated terminal. `.env.example` lists the variable names only.

`config/local.json` identifies the two CAN interfaces, three camera ASIC serials,
and account-accessible model checkpoint. The tested account used
`dreamlabs/dream-1-beta`; the generic default checkpoint is different. Do not
silently substitute checkpoints when an account rejects one.

```bash
uv run spill --config config/local.json run \
  "Pour all pills into the empty cup" \
  --hardware --zero-shot --grasp top-down --record
```

This energizes both arms and calls paid APIs. Without `--hardware` or `--shadow`,
the command uses mock cameras and joint echoes without API calls. `--shadow`
energizes the arms to hold; it is not an unpowered simulation.

Top-down grasping is passed to both models. It is a language constraint, not a
guarantee of physical orientation. Zero-shot mode disables table, obstacle and
inter-arm geometric checks. Viser uses nominal base placement in this mode.

Open **http://192.168.0.184:8080** for this cell, or
`http://<robot-host-ip>:8080`. Use HTTP, not HTTPS. Viser listens on all interfaces;
its page includes robot controls and should be accessible only to intended
operators on the trusted network. Its localhost banner does not restrict LAN access.

## Understand time and progress

At the configured 20 Hz, a 48-row Dream chunk represents 2.4 seconds of commanded
motion. The subtask budget counts motion, not API waiting. Execution finishes at
a chunk boundary: a 10-second budget can therefore report 12 seconds of motion.
That is expected and avoids cutting a prepared chunk before its terminal braking.

The first Dream request after an episode reset has often taken 4–5 seconds in
these trials; subsequent requests have often taken around 0.7–1.4 seconds. Those
are observations, not latency guarantees. Astra then receives new images to judge
progress. Its request timeout is 45 seconds with at most two transient retries
and 2/4-second backoff. The robot holds during these waits. The overall task
timeout still counts wall time, including inference and holds.

An `accepted` trajectory means the adapted commands passed the enabled guards.
It does not mean a cup was grasped or the task succeeded. Astra's visual judgments
are also fallible: occlusion, rim contact and camera angle can make grasp security
ambiguous. Success requires independent inspection, especially for tiny pills.

## Pause, stop and fault behavior

| Message/action | Meaning | Behavior |
|---|---|---|
| `Paused / holding: ... secure grasps cannot be confirmed` | Astra requested a pause | Arms hold; no further policy motion until Resume |
| Resume | Operator requests another assessment | Discard old predictions; acquire fresh observations and replan |
| Hold timeout | Pause exceeded 60 seconds | End the run; ordinary healthy-state shutdown parks |
| Ctrl+C / Home & Stop | Operator cancels with healthy feedback | Karma homes and then de-energizes |
| Second Ctrl+C / Stop Now | Cancel parking or stop immediately | De-energize in place |
| Feedback age exceeds 250 ms | Position feedback is not fresh enough to act on | Inhibit new actions, invalidate queued predictions and wait briefly |
| Feedback recovers within grace | Fresh measurements available again | Reobserve and replan; never resume the old chunk |
| Motor feedback reaches one second old, or grace expires | Sustained loss of trusted feedback | De-energize in place; do not attempt home |
| Temperature, native mode, camera or unrecoverable observation fault | Unsafe/unusable state | Stop in place |

Ctrl+C during an active feedback gap also skips homing. Native watchdogs and
hardware fault behavior remain authoritative; software cannot guarantee that
arms remain energized during a controller, power or communications failure.
The physical stop remains separate from Viser and terminal controls.

For a planner pause, inspect the scene before deciding whether to Resume. Do not
interpret repeated Resume clicks as a fix for an infeasible grasp. The models
cannot reliably establish grip force or count occluded pills from RGB alone.

## Diagnose before changing limits

```bash
uv run spill report runs/<run-id>
uv run spill replay runs/<run-id>
```

`report` reads local artifacts and writes `summary.json`; `replay` does not command
the real arms. Keep these events separate when reviewing a run:

- `astra_request`, `astra`, `astra_error`: planner input, decision, timing and errors.
- `dream_raw`, `dream`: predicted actions before/after gripper normalization.
- `accepted`, `command`: bounded trajectories and actually dispatched commands.
- `subtask_report`: actual motion, inference and wall time.
- `control`: pause, resume or replan reason.
- `feedback_gap`, `feedback_recovered`, `observation_fault`: feedback recovery or fault evidence.
- `result`: final outcome and termination reason.

Native node logs are under `logs/`. `ERROR-ACTIVE` in Linux CAN output is the
normal bus state, not an error alarm. Zero interface errors do not prove that
every motor replied or that its frames reached the correct driver cache. The
observed right-arm joint-1/joint-4 feedback losses remain unresolved. Distinguishing
motor reply loss from driver processing requires time-aligned CAN/native logs;
increasing the timeout is not a diagnosis.

## Recording and data integrity

With `--record`, observations and current commanded targets are archived during
motion and API holds. After motor shutdown, Karma's LeRobot v3 sink writes
`runs/<run-id>/lerobot_v3/`. Leave the process running until it prints the final
dataset path. Parking is not recorded. No upload occurs.

The v3 dataset has three RGB views and 14-element state/action vectors, left arm
first. Each arm contributes six radians and one gripper value. Native control uses
**1=open**, while Karma's dataset convention uses **0=open**; the exporter converts
both state and action values. Source timestamps are retained with causal 20 Hz
resampling; gaps over 200 ms split episodes. The `spill_rollout.json` sidecar marks
hardware/shadow status, partial failures, outcome and export completion. Never
treat the existence of a dataset as a successful demonstration label.

To package a complete older raw log:

```bash
uv run spill export-v3 runs/<run-id>
```

Existing datasets are not overwritten. Older logs without observer samples export
command segments only and declare that limitation. A truncated event log, empty
metadata file or missing completion marker means the artifact is incomplete;
preserve it for diagnosis instead of labeling it valid or deleting the evidence.

`runs/`, `logs/`, local configuration/calibration, environments and credentials are
excluded from Git. Commit source, tests, example configuration and documentation.
