# Validation and known limits — 2026-11-06

## Current software checks

The latest full offline suite passed **76 tests**. Targeted runtime/robot tests
also passed after the safety documentation update. Ruff checks passed.

Coverage includes bounded joint/acceleration/gripper execution, small initial
boundary recovery, transient feedback command inhibition, recovered-state
replanning, sustained feedback shutdown, cancellation during a gap, planner
timeout retries, stale-generation rejection, and real Karma LeRobot v3 output
with gripper-polarity conversion. A mock CLI run with `--record` produced videos
and Parquet after simulated motor shutdown. These are software checks, not a
physical reliability certification.

## Operator-run hardware observations

The operator has run real Astra/Dream requests, camera capture, bimanual motion,
pause/resume, normal homing and fault shutdown. Recorded real trials include:

| Run suffix | Observation |
|---|---|
| `142341-fd6eaa27` | 15 accepted chunks, 36 s commanded motion; an Astra progress check timed out |
| `144117-44d94055` | Right joint-1 feedback reached 273 ms; initial immediate-shutdown policy triggered; v3 dataset has 252 frames |
| `145816-739db2b0` | With grace handling, right joint-4 feedback reached 1,000 ms and fault shutdown occurred; v3 dataset has 404 frames |
| `145949-91c9d3e3` | Nine accepted chunks, 21.6 s commanded motion; Astra paused on uncertain grasp, operator resumed and later stopped |

The full IDs begin `20261106T`. See the [latest trial diagnosis](rollout-2026-11-06.md).
The newer trial with a clean home move does not resolve intermittent CAN/motor
feedback loss. One separate run (`144753-18ef0a6d`) has a damaged trailing event
record and empty v3 metadata; its completion and termination cause cannot be
established from those artifacts. Original files were retained.

Not established: reliable pill transfer, zero spills, independent exact pill
counts, calibrated collision clearance, physical emergency-stop validation,
or a twenty-trial success rate. Camera hand-eye calibration and task fine-tuning
have not been demonstrated. No real-robot success-rate claim is made.

## Initial implementation checks (historical)

Completed locally:

- `uv sync --locked --offline`: main Python 3.12 environment, 138 installed packages.
- `uv sync --locked --offline --project dream_runtime`: isolated Dream SDK,
  101 installed packages. `dream_ik.specs.EMBODIMENTS` includes YAM.
- Initial `uv run pytest -q`: **41 tests passed**, before later additions above.
- Ruff lint and formatting checks passed.
- Complete mock execution with Viser, three synthetic camera feeds, prediction
  overlays, subtask status, logging and shutdown completed without renderer errors.
- Recorded-run replay completed with and without Viser.
- Tests sent an actual SIGINT to a mock subprocess and exercised Karma's real
  `power_down` function with fake arms, including interrupted/failed parking.
- Tests checked late replies, cloud cancellation, camera failure, native state
  property access, stale per-motor feedback hidden behind fresh node messages,
  gripper hold semantics, action limits, swept collision sampling and overlay removal.
- Isolated SDK transport tests covered large pipe messages, errors, timeouts,
  process cleanup and pacing-table delivery. They used a stub service, not paid APIs.
- A synthetic LeRobot v2.1 export passed the installed official Dream validator:
  `ok=True`, one episode, 20 frames at 10 Hz, 14 state/action values and all three
  expected camera roles. Source 20 Hz data was explicitly downsampled.
- The calibrated path rejects unverified configuration. The later explicit
  `--zero-shot` path bypasses measured geometry and its verification flags.

At the initial implementation checkpoint, no physical tests or paid API calls had
been performed. The operator-run observations above supersede that historical
status; they do not turn a software test into a manipulation benchmark.

Mock mode is a joint echo with generated images, not a physics simulation. Passing
these checks establishes software behavior and dataset format; it does not
establish physical collision clearance or manipulation reliability.
