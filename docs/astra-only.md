# Astra-only control (experimental)

Spill now supports three controllers: the existing Astra planner plus Dream,
`--dream-only`, and `--astra-only`. The latter uses only `OPENAI_API_KEY` and the
configured Astra model. It never constructs the Dream client, calls Dream APIs,
or requires `DREAM_API_KEY`.

The design takes inspiration from the one-motion-per-observation agent in
[inspect-robots](https://github.com/robocurve/inspect-robots), inspected locally at
commit `7720195` (`plugins/inspect-robots-agent/.../policy.py`). No reference code
was copied and no dependency on that framework was introduced.

## Action contract

Astra sees three labeled RGB views, native joint/gripper state, joint limits,
the task, and recent execution reports. It returns a validated structured action
with explanation and evidence. Each execute decision selects one or both arms;
omitted arms retain their commanded targets. Each selected arm can request six
joint deltas of at most +/-0.12 radians each and a gripper-opening delta of at
most +/-0.1 (0 closed, 1 open). Targets outside joint/gripper limits are rejected,
not silently accepted. Repeated arm entries and motion on a non-execute action
are invalid. Pause, observe and finish remain available.

The local adapter produces a two-second quintic ramp at 20 Hz. The existing
trajectory guard then validates/bounds it before dispatch. Astra receives fresh
observations after every chunk; ordinary 20-second and recovery 7-second windows
do not apply. No action can be replayed: action tickets are consumed once and
must match the active control generation. Changes over 0.03 rad in a joint or
0.03 in opening/command anchor during planning reject the action. Original
observation timestamps are retained, so the existing prediction TTL can reject
a slow API response. Low reasoning effort is used for the direct-action mode;
the normal planner retains medium effort. Slow responses are not relabeled fresh.

This is joint-space control, not calibrated Cartesian grasping, IK-based pouring,
force control or a claim of superior performance. The model is told that camera
calibration and Cartesian displacement are not supplied. Zero-shot disables
geometric collision checks as before. Native safeguards, command cancellation,
feedback checks and shutdown handling remain in Karma/Spill.

## Test on the rig

First inspect proposed actions using the real cameras and held arms:

```bash
cd ~/karma/spill
uv run spill --config config/local.json run --astra-only --shadow --zero-shot --record
```

Shadow mode energizes/holds the real arms and uses paid Astra calls; it suppresses
policy motion. It is not a simulator and cannot verify task completion. Normal
startup/homing behavior still applies. Review the Viser trajectory and logs.

For a subsequent supervised physical trial:

```bash
uv run spill --config config/local.json run --astra-only --hardware --zero-shot --record
```

Both commands prompt for the task. `--astra-only` and `--dream-only` are mutually
exclusive. No hardware trial was launched while implementing this mode.

## Audit trail and verification

`controller` identifies the mode; existing `astra_request`, `astra_response`,
`decision`, `accepted`, `command` and dataset records remain available.
`astra_action` stores the selected moves, absolute targets, source observation
age and generation. A scene assessment or `finish` is not independent success
verification. History includes executed reports and images are archived.

Offline tests cover schema bounds, invalid/duplicate actions, changed anchors,
cancelled generations, one-use actions, inactive-arm preservation and the full
mock one-chunk-then-reobserve loop. Hardware efficacy and cloud parsing of this
new action schema still require validation. Retain the failing log if the API
rejects the schema or if model latency exceeds the trajectory TTL.
