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
uv run spill --config config/local.json run --hardware --zero-shot
# Task for this rollout: <type your instruction>
```

This energizes both arms and calls paid APIs. Without `--hardware` or `--shadow`,
the command uses mock cameras and joint echoes without API calls. `--shadow`
energizes the arms to hold; it is not an unpowered simulation.

Task entry happens before camera/model/motor startup. A task may alternatively be
provided as the positional argument. Astra receives general object-safety context
and your unchanged task; it chooses necessary objects and arms from the scene.
There is no default cup-specific or top-down instruction. The optional legacy
`--grasp top-down` flag adds that instruction explicitly; omit it for general tasks.
Zero-shot mode disables table, obstacle and
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

- `astra_request`, `astra_response`, `astra`, `astra_error`: planner input, full
  returned response, parsed decision, timing and errors.
- `dream_session`, `dream_tick`, `dream_request`, `dream_error`: subtask/config,
  encoded images and state submitted to the SDK, action request anchor and errors.
- `dream_raw`, `dream`: predicted actions before/after gripper normalization.
- `accepted`, `command`: bounded trajectories and actually dispatched commands.
- `subtask_report`: actual motion, inference and wall time.
- `control`: pause, resume or replan reason.
- `feedback_gap`, `feedback_recovered`, `observation_fault`: feedback recovery or fault evidence.
- `result`: final outcome and termination reason.

Native node logs are under `logs/`. `ERROR-ACTIVE` in Linux CAN output is the
normal bus state, not an error alarm. Zero interface errors do not prove that
every motor replied or that its frames reached the correct driver cache. The
2026-11-07 investigation found and fixed a native DM parser bug: it treated a
status position low byte of `0x55` as a register-write acknowledgement, dropping
valid feedback and leaving the cached timestamp stale. Register acknowledgements
are now distinguished by their CAN channel as well as opcode. An offline test
covers every position low byte on both supported status reply channels. Rebuild
the native Karma package after updating this source; Python editable installs
alone do not update the executable. This is a reproduced parser defect, not proof
that every earlier gap had this cause. Distinguishing remaining motor reply loss
from driver processing requires time-aligned CAN/native logs; increasing the
timeout is not a diagnosis. See [the episode investigation](feedback-2026-11-07.md).

## Recording and data integrity

Recording is on by default (`--no-record` opts out). Observations and current
commanded targets are archived during
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

## Stationary inspection loops

Run `20261107T110030-b671bd3d` executed eight Dream chunks (19.2 seconds of
commanded motion), then Astra repeatedly requested `observe` because rim contact
and cup support were occluded. This was an inspection-limit pause, not a CAN
shutdown. After Resume, the old observation counter caused another pause after
just one inspection. Ctrl+C subsequently homed both arms and stopped normally.
The recorded dataset is `local/20261107T110030-b671bd3d` (2603 frames).

The runtime now resets the inspection counter on control-generation changes,
including Resume. Each decision prints its action, latency, subtask, explanation,
evidence and instruction. `observe` prints its count out of three and explicitly
states that it acquires images without moving either the robot or cameras.
Structured `observation_wait` events retain this count and the reason; recent
inspection decisions also reach Astra through its history. Its instructions
explain that stationary inspection cannot necessarily resolve occlusion: choose
a distinct recovery only when current evidence supports safety, otherwise pause
and explain the missing evidence and needed operator intervention. Three
consecutive observation decisions still pause. Resume grants a fresh inspection
budget; it does not establish a secure grasp or guarantee progress.

## Planner errors and supported recovery

Run `20261107T110744-f54fe2d8` stopped planning after a 45.3-second API timeout
and a subsequent malformed-JSON validation error (30.8 seconds). The latter was
previously nonretryable. Its raw API response was not retained because SDK parsing
raised before returning it, so token-limit exhaustion is not established.
Malformed JSON now uses the existing bounded planner retry budget, holding with
fresh observations between attempts. Partial instructions are never executed.
Invalid schema field values remain nonretryable. Error logs now include validation
error details without the raw input payload. The timeout and malformed response
share the retry budget; neither resets it. Exhaustion still pauses.

Astra guidance now explicitly considers set-down, inspect support, release and
withdraw, then a different grasp as separate recovery steps. Set-down is skipped
if the object is already supported. Each step requires fresh visual evidence;
a held object is not released in midair and no blind descent is requested.
Execution history now retains the recovery flag, subtask, explanation and evidence;
the terminal prints recovery attempt counts. These are planner instructions using
the existing guarded Dream executor, not a guaranteed placement primitive or
force-controlled grasp. A safe recovery can still be unavailable, requiring pause.

## Dream execution window

`execution_window_s` now defaults to `20` seconds of commanded motion per ordinary Astra
execute decision. Recovery decisions (`recovery=true`) instead use
`recovery_window_s`, defaulting to 7 seconds. Dream continues receiving fresh observations and generating
short action chunks; this is not a 20-second open-loop trajectory. Astra reviews
at the first completed chunk after that budget. With 48 rows at 20 Hz, nine
chunks total 21.6 seconds; API waits add wall time. Motor/telemetry guards,
operator Pause and Ctrl+C can interrupt before the budget expires.

The planner receives the configured interval and is instructed to choose a
coherent subtask, hold after accomplishing it, and not rely on a shorter duration
for safety. This is language guidance, not a low-level task-completion detector.
Astra's visual checks for deformation, alignment and task completion occur less
often. Longer windows do not fix an incorrect grasp or camera occlusion.
`execution_window` events record requested and effective budgets. Set
`"execution_window_s": null` in your config to restore planner-selected timing,
or set a number from 1 to 30 to choose another interval.


Recovery windows also finish the current validated chunk: at 48 rows / 20 Hz,
a 7-second recovery budget normally executes three chunks (7.2 seconds), then
requests fresh Astra assessment. Ordinary execution remains 20 seconds (normally
21.6). Terminal output and `execution_window` events identify recovery windows.
The planner receives both settings and is instructed to label resets, withdrawal,
and retries after failure as recovery. This depends on planner classification;
it is not an automatic physical grasp-failure detector.

Localized rim pinches may legitimately put one finger just inside and one outside
the cup. Planner guidance no longer treats insertion alone as a failure: it must
consider localized engagement, deformation, contents clearance, an open pouring
edge and support. Insertion alone also does not prove secure contact. Unresolved
support or contact uncertainty can still justify holding. Motor safety limits and
operator controls are unchanged.

## Recorded top-camera gallery

Run `uv run spill --config config/local.json recordings --host 0.0.0.0 --port 8085`
and open `http://192.168.0.184:8085` from the LAN. This read-only service lists
runs newest first with their task prompts and all exported top-camera MP4 parts.
Refresh the page after a rollout finishes exporting. Runs without exported video
are explicitly marked; this service does not convert raw archives or show a live
camera stream. Video seeking is supported. Only the gallery and inventoried top
videos are served, not arbitrary run logs or configuration files. No API calls
or motor access are involved. The viewer has no authentication; devices able to
reach the port can read the displayed prompts and videos.
