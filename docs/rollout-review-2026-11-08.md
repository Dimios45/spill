# Dream-only and Astra + Dream rollout review

Snapshot: 2026-11-08. Scope excludes the unvalidated Astra-only controller and mock trials. Run IDs are UTC timestamps; local operator time is Asia/Shanghai. This review uses saved manifests, summaries and dataset metadata, plus explicitly attributed operator observations. It is not a claim that every video has been independently graded.

## Findings and interpretation

- Hybrid runs showed useful approach/grasp behavior but repeatedly paused on occlusion, grasp ambiguity or object deformation. Supported recovery prompts did not guarantee physical recovery.
- Dream-only removed planner interruptions, but previously reset the model session at every 20-second checkpoint. The current fix preserves session memory across ordinary checkpoints.
- Native DM feedback parsing, API timeouts/malformed responses, cloud capacity errors, and local timing/skew faults are separate failure classes.
- LeRobot imports reproduced >100 ms Python GC pauses. Dependency preflight is now isolated; long GC pauses are logged. This is evidence of a local contributor, not retrospective proof for every physical failure.
- Prompting stronger tilt or wrist-view use does not guarantee alignment or fix command timing. Zero-shot disables geometric collision checks.
- Model-assessed success and operator praise are not independent success labels. Dream-only stopped runs remain unverified.

## Changes since Spill commit `948c99f`

Included: minor rim-flex guidance; detailed skew/deadline diagnostics; delayed-acquisition rejection; conditional motor-checked homing on skew faults; isolated LeRobot preflight; GC timing telemetry; continuous Dream-only sessions; regression tests and investigation docs.

Excluded: Astra-only CLI selection, direct-action schema/provider, two-second single-step execution integration, its tests and documentation. The older 20-second execution / 7-second recovery settings, rollout catalog and viewer are already in the baseline commit.

## Important episodes

### 20261106T142341-fd6eaa27 — Astra + Dream

Dataset: `local/20261106T142341-fd6eaa27`; exported frames: not available. Commanded motion: 36.0 s. Outcome: **unverified**. Termination: Stopped by operator.

**Exact task prompt:**

> Pour all pills into the empty cup

Early hybrid execution; operator reported useful progress, followed by a planner timeout. Transfer not verified.

[Episode decisions](../runs/20261106T142341-fd6eaa27/episode.md) · [Summary](../runs/20261106T142341-fd6eaa27/summary.json) · [API/event log](../runs/20261106T142341-fd6eaa27/events.jsonl) · [Model I/O index](../runs/20261106T142341-fd6eaa27/model_io_index.json) · [Dataset](../runs/20261106T142341-fd6eaa27/lerobot_v3) · [Top video](../runs/20261106T142341-fd6eaa27/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261106T145816-739db2b0 — Astra + Dream

Dataset: `local/20261106T145816-739db2b0`; exported frames: 404. Commanded motion: 4.8 s. Outcome: **failed**. Termination: SafetyError: Observation service failed: right stale motor CAN feedback: joint_4=1000.0ms; limit=250ms.

**Exact task prompt:**

> Pour all pills into the empty cup Approach and grasp each cup from above with a top-down gripper orientation; do not use a sideways approach. Keep the cup upright until positioned over the receiving cup, and tilt only for pouring. If a top-down grasp is not feasible, pause instead of switching to a sideways grasp.

Persistent right motor-feedback loss; stopped in place. See the native parser investigation.

[Episode decisions](../runs/20261106T145816-739db2b0/episode.md) · [Summary](../runs/20261106T145816-739db2b0/summary.json) · [API/event log](../runs/20261106T145816-739db2b0/events.jsonl) · [Model I/O index](../runs/20261106T145816-739db2b0/model_io_index.json) · [Dataset](../runs/20261106T145816-739db2b0/lerobot_v3) · [Top video](../runs/20261106T145816-739db2b0/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261107T101729-6bbb5b03 — Astra + Dream

Dataset: `local/20261107T101729-6bbb5b03`; exported frames: 3651. Commanded motion: 43.2 s. Outcome: **unverified**. Termination: Stopped by operator.

**Exact task prompt:**

> transfer the pills from one cup to the other

Reference episode: operator reported the paper cup was pinched closed, preventing pills from falling. Historical prompt context is not policy training.

[Episode decisions](../runs/20261107T101729-6bbb5b03/episode.md) · [Summary](../runs/20261107T101729-6bbb5b03/summary.json) · [API/event log](../runs/20261107T101729-6bbb5b03/events.jsonl) · [Model I/O index](../runs/20261107T101729-6bbb5b03/model_io_index.json) · [Dataset](../runs/20261107T101729-6bbb5b03/lerobot_v3) · [Top video](../runs/20261107T101729-6bbb5b03/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261107T104500-7bfa00b6 — Astra + Dream

Dataset: `local/20261107T104500-7bfa00b6`; exported frames: 951. Commanded motion: 15.6 s. Outcome: **failed**. Termination: SafetyError: Observation service failed: right stale motor CAN feedback: joint_2=1007.0ms; limit=250ms.

**Exact task prompt:**

> transfer the pills from one cup to the other but grasp the cup from top down as it is a paper cup and will get crushed if you grasp it horizontally then just tilt the cup with the pills such that the pills fall into the empty cup

Right joint-2 telemetry reached 1007 ms. Native parser defect reproduced offline; raw CAN was not captured to prove this episode had that cause.

[Episode decisions](../runs/20261107T104500-7bfa00b6/episode.md) · [Summary](../runs/20261107T104500-7bfa00b6/summary.json) · [API/event log](../runs/20261107T104500-7bfa00b6/events.jsonl) · [Model I/O index](../runs/20261107T104500-7bfa00b6/model_io_index.json) · [Dataset](../runs/20261107T104500-7bfa00b6/lerobot_v3) · [Top video](../runs/20261107T104500-7bfa00b6/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261107T110030-b671bd3d — Astra + Dream

Dataset: `local/20261107T110030-b671bd3d`; exported frames: 2603. Commanded motion: 19.2 s. Outcome: **unverified**. Termination: Stopped by operator.

**Exact task prompt:**

> Transfer the pills from one cup to the other, but grasp the cup from top down as it is a paper cup and will get crushed if you grasp it horizontally. Then tilt the cup with the pills such that the pills
>   fall into the empty cup.

Three stationary observe decisions paused execution. Resume retained the old counter; subsequently fixed. Occlusion remained a perception limitation.

[Episode decisions](../runs/20261107T110030-b671bd3d/episode.md) · [Summary](../runs/20261107T110030-b671bd3d/summary.json) · [API/event log](../runs/20261107T110030-b671bd3d/events.jsonl) · [Model I/O index](../runs/20261107T110030-b671bd3d/model_io_index.json) · [Dataset](../runs/20261107T110030-b671bd3d/lerobot_v3) · [Top video](../runs/20261107T110030-b671bd3d/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261107T110744-f54fe2d8 — Astra + Dream

Dataset: `local/20261107T110744-f54fe2d8`; exported frames: 2957. Commanded motion: 19.2 s. Outcome: **unverified**. Termination: Stopped by operator.

**Exact task prompt:**

> Transfer the pills from one cup to the other, but grasp the cup from top down from its rim  as it is a paper cup
>   and will get crushed if you grasp it horizontally. Then tilt the cup with the pills such that the pills
>   fall into the empty cup.

Planner timeout followed by malformed JSON. Added bounded retry for json_invalid; invalid decisions never become motion.

[Episode decisions](../runs/20261107T110744-f54fe2d8/episode.md) · [Summary](../runs/20261107T110744-f54fe2d8/summary.json) · [API/event log](../runs/20261107T110744-f54fe2d8/events.jsonl) · [Model I/O index](../runs/20261107T110744-f54fe2d8/model_io_index.json) · [Dataset](../runs/20261107T110744-f54fe2d8/lerobot_v3) · [Top video](../runs/20261107T110744-f54fe2d8/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261107T111420-1ab7f3b1 — Astra + Dream

Dataset: `local/20261107T111420-1ab7f3b1`; exported frames: 2480. Commanded motion: 16.8 s. Outcome: **unverified**. Termination: Hold timeout.

**Exact task prompt:**

> Transfer the pills from one cup to the other, but grasp the cup from top down as it is a paper cup
>   and will get crushed if you grasp it horizontally. Then tilt the cup with the pills such that the pills
>   fall into the empty cup.

Grasp/support uncertainty caused a deliberate pause. Prior inspection found opposing-side finger placement and substantial raw-to-bounded trajectory changes; no verified rim grasp.

[Episode decisions](../runs/20261107T111420-1ab7f3b1/episode.md) · [Summary](../runs/20261107T111420-1ab7f3b1/summary.json) · [API/event log](../runs/20261107T111420-1ab7f3b1/events.jsonl) · [Model I/O index](../runs/20261107T111420-1ab7f3b1/model_io_index.json) · [Dataset](../runs/20261107T111420-1ab7f3b1/lerobot_v3) · [Top video](../runs/20261107T111420-1ab7f3b1/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261107T112141-98b08f07 — Astra + Dream

Dataset: `local/20261107T112141-98b08f07`; exported frames: 3485. Commanded motion: 31.2 s. Outcome: **unverified**. Termination: Stopped by operator.

**Exact task prompt:**

> Transfer the pills from one cup to the other, but grasp the cup from top down as it is a paper cup and will get crushed if you grasp it horizontally. Then tilt the cup with the pills such that the pills
>   fall into the empty cup.

Operator reported useful grasp/tilt but suspected pouring at the wrong location. Model later paused because supported reset could not be confirmed. No verified transfer.

[Episode decisions](../runs/20261107T112141-98b08f07/episode.md) · [Summary](../runs/20261107T112141-98b08f07/summary.json) · [API/event log](../runs/20261107T112141-98b08f07/events.jsonl) · [Model I/O index](../runs/20261107T112141-98b08f07/model_io_index.json) · [Dataset](../runs/20261107T112141-98b08f07/lerobot_v3) · [Top video](../runs/20261107T112141-98b08f07/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261107T115637-0869afad — Astra + Dream

Dataset: `local/20261107T115637-0869afad`; exported frames: 3621. Commanded motion: 50.4 s. Outcome: **unverified**. Termination: Hold timeout.

**Exact task prompt:**

> Transfer the ping-pong ball into the empty cup. Approach from above and gently pinch a small section of the source cup's rim, with one finger just inside and one outside, clear of the ball. Preserve the
>   cup's shape and opening. Leave the receiving cup on the table. Position the pouring edge over its opening before slowly tilting. Verify transfer, then return the source cup upright to the table. If recovery is
>   needed, keep the cup supported and reassess before releasing or regrasping.

Ping-pong transfer with rim-grasp instructions; recovery/withdrawal did not establish clear engagement. This motivated distinguishing expected finger insertion from damage.

[Episode decisions](../runs/20261107T115637-0869afad/episode.md) · [Summary](../runs/20261107T115637-0869afad/summary.json) · [API/event log](../runs/20261107T115637-0869afad/events.jsonl) · [Model I/O index](../runs/20261107T115637-0869afad/model_io_index.json) · [Dataset](../runs/20261107T115637-0869afad/lerobot_v3) · [Top video](../runs/20261107T115637-0869afad/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261107T121539-9cdada40 — Astra + Dream

Dataset: `local/20261107T121539-9cdada40`; exported frames: 371. Commanded motion: 0.0 s. Outcome: **unverified**. Termination: Stopped by operator.

**Exact task prompt:**

> Transfer the ping-pong ball into the empty cup. Approach from above and gently pinch a small section of the source cup's rim, with one finger just inside and one outside, clear of the ball. Preserve the
>   cup's shape and opening. Leave the receiving cup on the table. Position the pouring edge over its opening before slowly tilting. Verify transfer, then return the source cup upright to the table. If recovery is
>   needed, keep the cup supported and reassess before releasing or regrasping.

Dream capacity refusal (DA-2000 NO_CAPACITY), distinct from local timing failures. No commanded motion recorded.

[Episode decisions](../runs/20261107T121539-9cdada40/episode.md) · [Summary](../runs/20261107T121539-9cdada40/summary.json) · [API/event log](../runs/20261107T121539-9cdada40/events.jsonl) · [Model I/O index](../runs/20261107T121539-9cdada40/model_io_index.json) · [Dataset](../runs/20261107T121539-9cdada40/lerobot_v3) · [Top video](../runs/20261107T121539-9cdada40/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261107T130342-ca38c235 — Astra + Dream

Dataset: `local/20261107T130342-ca38c235`; exported frames: 1957. Commanded motion: 43.2 s. Outcome: **success**. Termination: The overhead and wrist views show overlapping towel layers with slightly uneven edges, no suspended fabric, and both open grippers clear of the towel..

**Exact task prompt:**

> fold the towel

Different task: towel folding. Logged success is the planner assessment, not independent benchmark verification; do not count it as cup-transfer success.

[Episode decisions](../runs/20261107T130342-ca38c235/episode.md) · [Summary](../runs/20261107T130342-ca38c235/summary.json) · [API/event log](../runs/20261107T130342-ca38c235/events.jsonl) · [Model I/O index](../runs/20261107T130342-ca38c235/model_io_index.json) · [Dataset](../runs/20261107T130342-ca38c235/lerobot_v3) · [Top video](../runs/20261107T130342-ca38c235/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261108T082620-73dcacc4 — Dream-only

Dataset: `local/20261108T082620-73dcacc4`; exported frames: 793. Commanded motion: 26.6 s. Outcome: **failed**. Termination: SafetyError: Observation service failed: Camera/state time skew exceeds limit.

**Exact task prompt:**

> Transfer the pills from one cup to the other, but grasp the cup from top down as it is a paper cup and will get crushed if you grasp it horizontally. Then tilt the cup with the pills such that the pills   fall into the empty cup.

Dream-only: execution deadline miss followed by skew fault. Original fault log lacked the failing snapshot timestamps; richer timing diagnostics added.

[Episode decisions](../runs/20261108T082620-73dcacc4/episode.md) · [Summary](../runs/20261108T082620-73dcacc4/summary.json) · [API/event log](../runs/20261108T082620-73dcacc4/events.jsonl) · [Model I/O index](../runs/20261108T082620-73dcacc4/model_io_index.json) · [Dataset](../runs/20261108T082620-73dcacc4/lerobot_v3) · [Top video](../runs/20261108T082620-73dcacc4/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261108T083014-1083a2bb — Dream-only

Dataset: `local/20261108T083014-1083a2bb`; exported frames: 938. Commanded motion: 31.35 s. Outcome: **failed**. Termination: SafetyError: Observation service failed: Camera/state time skew exceeds limit: 173.1ms > 100ms; ages: camera.top=173.5ms, camera.left_wrist=149.2ms, camera.right_wrist=0.5ms, state.left=147.4ms, state.right=149.1ms.

**Exact task prompt:**

> Transfer the pills from one cup to the other, but grasp the cup from top down as it is a paper cup and will get crushed if you grasp it horizontally. Then tilt the cup with the pills such that the pills   fall into the empty cup.

173.1 ms skew and 105.7 ms execution lateness. Different input ages implicated local observation timing, not an Astra decision.

[Episode decisions](../runs/20261108T083014-1083a2bb/episode.md) · [Summary](../runs/20261108T083014-1083a2bb/summary.json) · [API/event log](../runs/20261108T083014-1083a2bb/events.jsonl) · [Model I/O index](../runs/20261108T083014-1083a2bb/model_io_index.json) · [Dataset](../runs/20261108T083014-1083a2bb/lerobot_v3) · [Top video](../runs/20261108T083014-1083a2bb/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261108T083523-ca66f9b7 — Dream-only

Dataset: `local/20261108T083523-ca66f9b7`; exported frames: 1057. Commanded motion: 36.15 s. Outcome: **failed**. Termination: SafetyError: Observation service failed: Camera/state time skew exceeds limit: 172.3ms > 100ms; ages: camera.top=173.0ms, camera.left_wrist=0.7ms, camera.right_wrist=0.8ms, state.left=146.1ms, state.right=146.2ms.

**Exact task prompt:**

> Transfer the ping-pong ball into the empty cup. Approach from above and gently pinch a small section of the source cup's rim, with one finger just inside and one outside, clear of the ball. Preserve the

Acquisition-duration retry did not catch cached old state delivered with fresh frames. Added conditional motor-checked homing specifically for skew faults.

[Episode decisions](../runs/20261108T083523-ca66f9b7/episode.md) · [Summary](../runs/20261108T083523-ca66f9b7/summary.json) · [API/event log](../runs/20261108T083523-ca66f9b7/events.jsonl) · [Model I/O index](../runs/20261108T083523-ca66f9b7/model_io_index.json) · [Dataset](../runs/20261108T083523-ca66f9b7/lerobot_v3) · [Top video](../runs/20261108T083523-ca66f9b7/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261108T092914-176e221b — Dream-only

Dataset: `local/20261108T092914-176e221b`; exported frames: 1039. Commanded motion: 35.65 s. Outcome: **unverified**. Termination: Stopped by operator.

**Exact task prompt:**

> Transfer the ping-pong ball from the source cup into the empty cup. Approach from above and gently
>   pinch a small section of the source cup's rim, with one finger just inside and one outside, clear of
>   the ball. Preserve the cup's shape and leave its opening unobstructed. Keep the receiving cup on the
>   table. Position the source cup's pouring edge over the receiving cup's opening, then tilt slowly. If
>   the ball does not roll, gradually increase the tilt while maintaining alignment and a stable grasp. If
>   the ball is trapped by a finger or deformed rim, stop and reassess rather than forcing it. Once the
>   ball lands inside the receiving cup, return the source cup upright to the table. Confirm support before
>   releasing.

Prompt requested increasing tilt; operator still reported inadequate pouring. Accepted trajectories alone do not verify cup pose or transfer.

[Episode decisions](../runs/20261108T092914-176e221b/episode.md) · [Summary](../runs/20261108T092914-176e221b/summary.json) · [API/event log](../runs/20261108T092914-176e221b/events.jsonl) · [Model I/O index](../runs/20261108T092914-176e221b/model_io_index.json) · [Dataset](../runs/20261108T092914-176e221b/lerobot_v3) · [Top video](../runs/20261108T092914-176e221b/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261108T111950-a9505e49 — Dream-only

Dataset: `local/20261108T111950-a9505e49`; exported frames: 2162. Commanded motion: 63.0 s. Outcome: **unverified**. Termination: Stopped by operator.

**Exact task prompt:**

> Transfer the pills from one cup to the other, but grasp the cup from top down as it is a paper cup
>   and will get crushed if you grasp it horizontally. Then tilt the cup with the pills such that the pills
>   fall into the empty cup.

Operator-ended Dream-only comparison episode; available in the rollout viewer. No independently verified transfer recorded.

[Episode decisions](../runs/20261108T111950-a9505e49/episode.md) · [Summary](../runs/20261108T111950-a9505e49/summary.json) · [API/event log](../runs/20261108T111950-a9505e49/events.jsonl) · [Model I/O index](../runs/20261108T111950-a9505e49/model_io_index.json) · [Dataset](../runs/20261108T111950-a9505e49/lerobot_v3) · [Top video](../runs/20261108T111950-a9505e49/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261108T114420-24289ff7 — Dream-only

Dataset: `local/20261108T114420-24289ff7`; exported frames: 2059. Commanded motion: 71.3 s. Outcome: **unverified**. Termination: Stopped by operator.

**Exact task prompt:**

> Transfer the pills from one cup to the other, but grasp the cup from top down as it is a paper cup
>   and will get crushed if you grasp it horizontally. Then tilt the cup with the pills such that the pills
>   fall into the empty cup.

Operator described this as useful progress and requested more tilt. Recorded outcome remains unverified.

[Episode decisions](../runs/20261108T114420-24289ff7/episode.md) · [Summary](../runs/20261108T114420-24289ff7/summary.json) · [API/event log](../runs/20261108T114420-24289ff7/events.jsonl) · [Model I/O index](../runs/20261108T114420-24289ff7/model_io_index.json) · [Dataset](../runs/20261108T114420-24289ff7/lerobot_v3) · [Top video](../runs/20261108T114420-24289ff7/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261108T115614-f7831f00 — Dream-only

Dataset: `local/20261108T115614-f7831f00`; exported frames: 949. Commanded motion: 31.65 s. Outcome: **failed**. Termination: ObservationSkewError: Camera/state time skew exceeds limit: 151.4ms > 100ms; ages: camera.top=0.1ms, camera.left_wrist=0.2ms, camera.right_wrist=0.7ms, state.left=2.9ms, state.right=151.5ms.

**Exact task prompt:**

> Transfer the pills from the source cup into the empty cup. Approach from above and gently grasp the
>   source cup near its rim without crushing its walls or blocking its opening. Leave the receiving cup on
>   the table. Position the source cup's pouring edge over the receiving cup's opening. Slowly increase the
>   tilt while maintaining alignment and a stable grasp. If pills remain, continue tilting toward an almost
>   upside-down orientation, provided the pouring opening stays over the receiving cup and the cups and
>   gripper remain clear of collisions. Do not stop at a shallow tilt if pills remain and further rotation
>   is feasible. If pills are trapped by the gripper or a folded rim, stop rather than forcing the
>   rotation. Once transfer is complete, return the source cup upright, set it on the table, and release
>   only when supported.

Increased-tilt prompt; timing fault triggered healthy-motor homing then power off. Prompt changes do not repair timestamp skew.

[Episode decisions](../runs/20261108T115614-f7831f00/episode.md) · [Summary](../runs/20261108T115614-f7831f00/summary.json) · [API/event log](../runs/20261108T115614-f7831f00/events.jsonl) · [Model I/O index](../runs/20261108T115614-f7831f00/model_io_index.json) · [Dataset](../runs/20261108T115614-f7831f00/lerobot_v3) · [Top video](../runs/20261108T115614-f7831f00/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261108T120921-ab1d54fb — Dream-only

Dataset: `local/20261108T120921-ab1d54fb`; exported frames: 798. Commanded motion: 26.75 s. Outcome: **failed**. Termination: ObservationSkewError: Camera/state time skew exceeds limit: 177.6ms > 100ms; ages: camera.top=0.3ms, camera.left_wrist=174.3ms, camera.right_wrist=177.9ms, state.left=151.6ms, state.right=150.7ms.

**Exact task prompt:**

> Transfer the pills from the source cup into the empty cup. Approach from above and gently grasp the
>   source cup near its rim without crushing its walls or blocking its opening. Leave the receiving cup on
>   the table. Use all three camera views together. When the top camera cannot see the cup because an arm
>   or gripper obscures it, use the wrist-camera views to assess the grasp, cup opening, remaining pills,
>   and alignment with the receiving cup. Do not treat top-camera occlusion alone as task failure; pause if
>   the necessary details are unclear in every view. Position the source cup's pouring edge over the
>   receiving cup's opening. Slowly increase the tilt while maintaining alignment and a stable grasp. If
>   pills remain, continue toward an almost upside-down orientation while keeping the pouring opening above
>   the receiving cup and avoiding collisions. If pills are trapped by the gripper or a folded rim, stop
>   rather than forcing rotation. Once transfer is complete, return the source cup upright, set it on the
>   table, and release only when supported.

Repeated skew/deadline failure led to local GC investigation and isolated export preflight.

[Episode decisions](../runs/20261108T120921-ab1d54fb/episode.md) · [Summary](../runs/20261108T120921-ab1d54fb/summary.json) · [API/event log](../runs/20261108T120921-ab1d54fb/events.jsonl) · [Model I/O index](../runs/20261108T120921-ab1d54fb/model_io_index.json) · [Dataset](../runs/20261108T120921-ab1d54fb/lerobot_v3) · [Top video](../runs/20261108T120921-ab1d54fb/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261108T122025-15878dc6 — Dream-only

Dataset: `local/20261108T122025-15878dc6`; exported frames: 1668. Commanded motion: 61.9 s. Outcome: **unverified**. Termination: Stopped by operator.

**Exact task prompt:**

> Transfer the pills from the source cup into the empty cup. Approach from above and gently grasp the
>   source cup near its rim without crushing its walls or blocking its opening. Leave the receiving cup on
>   the table. Use all three camera views together. When the top camera cannot see the cup because an arm
>   or gripper obscures it, use the wrist-camera views to assess the grasp, cup opening, remaining pills,
>   and alignment with the receiving cup. Do not treat top-camera occlusion alone as task failure; pause if
>   the necessary details are unclear in every view. Position the source cup's pouring edge over the
>   receiving cup's opening. Slowly increase the tilt while maintaining alignment and a stable grasp. If
>   pills remain, continue toward an almost upside-down orientation while keeping the pouring opening above
>   the receiving cup and avoiding collisions. If pills are trapped by the gripper or a folded rim, stop
>   rather than forcing rotation. Once transfer is complete, return the source cup upright, set it on the
>   table, and release only when supported.

Post-fix physical episode; operator-ended. Inspect logs rather than infer success from duration.

[Episode decisions](../runs/20261108T122025-15878dc6/episode.md) · [Summary](../runs/20261108T122025-15878dc6/summary.json) · [API/event log](../runs/20261108T122025-15878dc6/events.jsonl) · [Model I/O index](../runs/20261108T122025-15878dc6/model_io_index.json) · [Dataset](../runs/20261108T122025-15878dc6/lerobot_v3) · [Top video](../runs/20261108T122025-15878dc6/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261108T122607-51caae26 — Dream-only

Dataset: `local/20261108T122607-51caae26`; exported frames: 1123. Commanded motion: 41.05 s. Outcome: **unverified**. Termination: Stopped by operator.

**Exact task prompt:**

> Transfer the pills from the source cup into the empty cup. Approach from above and gently grasp the
>   source cup near its rim without crushing its walls or blocking its opening. Leave the receiving cup on
>   the table. Use all three camera views together. When the top camera cannot see the cup because an arm
>   or gripper obscures it, use the wrist-camera views to assess the grasp, cup opening, remaining pills,
>   and alignment with the receiving cup. Do not treat top-camera occlusion alone as task failure; pause if
>   the necessary details are unclear in every view. Position the source cup's pouring edge over the
>   receiving cup's opening. Slowly increase the tilt while maintaining alignment and a stable grasp. If
>   pills remain, continue toward an almost upside-down orientation while keeping the pouring opening above
>   the receiving cup and avoiding collisions. If pills are trapped by the gripper or a folded rim, stop
>   rather than forcing rotation. Once transfer is complete, return the source cup upright, set it on the
>   table, and release only when supported.

Post-fix episode selected by the operator for a three-camera collage. Ended by operator; success remains unverified.

[Episode decisions](../runs/20261108T122607-51caae26/episode.md) · [Summary](../runs/20261108T122607-51caae26/summary.json) · [API/event log](../runs/20261108T122607-51caae26/events.jsonl) · [Model I/O index](../runs/20261108T122607-51caae26/model_io_index.json) · [Dataset](../runs/20261108T122607-51caae26/lerobot_v3) · [Top video](../runs/20261108T122607-51caae26/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

### 20261108T123154-123ca6ff — Dream-only

Dataset: `local/20261108T123154-123ca6ff`; exported frames: 1440. Commanded motion: 53.4 s. Outcome: **unverified**. Termination: Stopped by operator.

**Exact task prompt:**

> Transfer the pills from the source cup into the empty cup. Approach from above and gently grasp the
>   source cup near its rim without crushing its walls or blocking its opening. Leave the receiving cup on
>   the table. Use all three camera views together. When the top camera cannot see the cup because an arm
>   or gripper obscures it, use the wrist-camera views to assess the grasp, cup opening, remaining pills,
>   and alignment with the receiving cup. Do not treat top-camera occlusion alone as task failure; pause if
>   the necessary details are unclear in every view. Position the source cup's pouring edge over the
>   receiving cup's opening. Slowly increase the tilt while maintaining alignment and a stable grasp. If
>   pills remain, continue toward an almost upside-down orientation while keeping the pouring opening above
>   the receiving cup and avoiding collisions. If pills are trapped by the gripper or a folded rim, stop
>   rather than forcing rotation. Once transfer is complete, return the source cup upright, set it on the
>   table, and release only when supported.

Later post-fix physical episode; operator-ended. Included as additional timing follow-up, not a success label.

[Episode decisions](../runs/20261108T123154-123ca6ff/episode.md) · [Summary](../runs/20261108T123154-123ca6ff/summary.json) · [API/event log](../runs/20261108T123154-123ca6ff/events.jsonl) · [Model I/O index](../runs/20261108T123154-123ca6ff/model_io_index.json) · [Dataset](../runs/20261108T123154-123ca6ff/lerobot_v3) · [Top video](../runs/20261108T123154-123ca6ff/lerobot_v3/videos/observation.images.top/chunk-000/file-000.mp4)

## All completed physical Dream/hybrid runs with readable metadata

Local links resolve on the workstation; ignored recordings are not included in this documentation commit. Logs contain exact prompts, API inputs/outputs and action traces. No credentials or encoded images are copied into this review.

| Run | Mode | Dataset frames | Motion s | Outcome / termination |
|---|---|---:|---:|---|
| [20261106T142341-fd6eaa27](../runs/20261106T142341-fd6eaa27/episode.md) | Astra + Dream | — | 36.0 | unverified: Stopped by operator |
| [20261106T142949-5cbe00b9](../runs/20261106T142949-5cbe00b9/episode.md) | Astra + Dream | — | 19.2 | failed: SafetyError: Observation service failed: right stale motor CAN feedback behind fresh node messages |
| [20261106T144117-44d94055](../runs/20261106T144117-44d94055/episode.md) | Astra + Dream | 252 | 0.4 | failed: SafetyError: Observation service failed: right stale motor CAN feedback: joint_1=273.0ms; limit=250ms |
| [20261106T145816-739db2b0](../runs/20261106T145816-739db2b0/episode.md) | Astra + Dream | 404 | 4.8 | failed: SafetyError: Observation service failed: right stale motor CAN feedback: joint_4=1000.0ms; limit=250ms |
| [20261106T145949-91c9d3e3](../runs/20261106T145949-91c9d3e3/episode.md) | Astra + Dream | 2200 | 21.6 | unverified: Stopped by operator |
| [20261107T101729-6bbb5b03](../runs/20261107T101729-6bbb5b03/episode.md) | Astra + Dream | 3651 | 43.2 | unverified: Stopped by operator |
| [20261107T104044-a740dc33](../runs/20261107T104044-a740dc33/episode.md) | Astra + Dream | 2624 | 22.95 | unverified: Stopped by operator |
| [20261107T104500-7bfa00b6](../runs/20261107T104500-7bfa00b6/episode.md) | Astra + Dream | 951 | 15.6 | failed: SafetyError: Observation service failed: right stale motor CAN feedback: joint_2=1007.0ms; limit=250ms |
| [20261107T105342-e904799a](../runs/20261107T105342-e904799a/episode.md) | Astra + Dream | 1140 | 19.2 | unverified: Stopped by operator |
| [20261107T110030-b671bd3d](../runs/20261107T110030-b671bd3d/episode.md) | Astra + Dream | 2603 | 19.2 | unverified: Stopped by operator |
| [20261107T110744-f54fe2d8](../runs/20261107T110744-f54fe2d8/episode.md) | Astra + Dream | 2957 | 19.2 | unverified: Stopped by operator |
| [20261107T111420-1ab7f3b1](../runs/20261107T111420-1ab7f3b1/episode.md) | Astra + Dream | 2480 | 16.8 | unverified: Hold timeout |
| [20261107T112141-98b08f07](../runs/20261107T112141-98b08f07/episode.md) | Astra + Dream | 3485 | 31.2 | unverified: Stopped by operator |
| [20261107T112652-69d4b99a](../runs/20261107T112652-69d4b99a/episode.md) | Astra + Dream | 1892 | 12.0 | unverified: Stopped by operator |
| [20261107T112914-103c9c0f](../runs/20261107T112914-103c9c0f/episode.md) | Astra + Dream | 2248 | 19.2 | unverified: Stopped by operator |
| [20261107T113331-1c21afba](../runs/20261107T113331-1c21afba/episode.md) | Astra + Dream | 1085 | 21.6 | unverified: Stopped by operator |
| [20261107T113509-567ad6b0](../runs/20261107T113509-567ad6b0/episode.md) | Astra + Dream | 890 | 21.6 | unverified: Stopped by operator |
| [20261107T113631-24756f13](../runs/20261107T113631-24756f13/episode.md) | Astra + Dream | 733 | 17.85 | unverified: Stopped by operator |
| [20261107T113752-25b80458](../runs/20261107T113752-25b80458/episode.md) | Astra + Dream | 5558 | 43.2 | unverified: Hold timeout |
| [20261107T115441-938807d2](../runs/20261107T115441-938807d2/episode.md) | Astra + Dream | 1568 | 0.0 | unverified: Hold timeout |
| [20261107T115637-0869afad](../runs/20261107T115637-0869afad/episode.md) | Astra + Dream | 3621 | 50.4 | unverified: Hold timeout |
| [20261107T120601-438d1d64](../runs/20261107T120601-438d1d64/episode.md) | Astra + Dream | 3263 | 36.0 | unverified: Hold timeout |
| [20261107T121037-a004c059](../runs/20261107T121037-a004c059/episode.md) | Astra + Dream | 2276 | 0.0 | unverified: Stopped by operator |
| [20261107T121324-1293a6f6](../runs/20261107T121324-1293a6f6/episode.md) | Astra + Dream | 1264 | 0.0 | unverified: Stopped by operator |
| [20261107T121539-9cdada40](../runs/20261107T121539-9cdada40/episode.md) | Astra + Dream | 371 | 0.0 | unverified: Stopped by operator |
| [20261107T130342-ca38c235](../runs/20261107T130342-ca38c235/episode.md) | Astra + Dream | 1957 | 43.2 | success: The overhead and wrist views show overlapping towel layers with slightly uneven edges, no suspended fabric, and both open grippers clear of the towel. |
| [20261108T081944-559a2df1](../runs/20261108T081944-559a2df1/episode.md) | Astra + Dream | 1578 | 21.6 | unverified: Stopped by operator |
| [20261108T082203-80aafc6f](../runs/20261108T082203-80aafc6f/episode.md) | Astra + Dream | 2831 | 36.0 | unverified: Stopped by operator |
| [20261108T082620-73dcacc4](../runs/20261108T082620-73dcacc4/episode.md) | Dream-only | 793 | 26.6 | failed: Camera/state skew fault |
| [20261108T083014-1083a2bb](../runs/20261108T083014-1083a2bb/episode.md) | Dream-only | 938 | 31.35 | failed: Camera/state skew fault |
| [20261108T083339-0f1f47a0](../runs/20261108T083339-0f1f47a0/episode.md) | Dream-only | 1037 | 31.3 | unverified: Stopped by operator |
| [20261108T083523-ca66f9b7](../runs/20261108T083523-ca66f9b7/episode.md) | Dream-only | 1057 | 36.15 | failed: Camera/state skew fault |
| [20261108T084015-14f5347d](../runs/20261108T084015-14f5347d/episode.md) | Dream-only | 679 | 22.15 | unverified: Stopped by operator |
| [20261108T084132-41587720](../runs/20261108T084132-41587720/episode.md) | Dream-only | 501 | 17.25 | unverified: Stopped by operator |
| [20261108T084240-f763b9f9](../runs/20261108T084240-f763b9f9/episode.md) | Dream-only | 4044 | 102.35 | unverified: Stopped by operator |
| [20261108T084737-cf28cc10](../runs/20261108T084737-cf28cc10/episode.md) | Dream-only | 2233 | 55.35 | unverified: Stopped by operator |
| [20261108T085027-8ca9c2ea](../runs/20261108T085027-8ca9c2ea/episode.md) | Dream-only | 876 | 28.95 | failed: Camera/state skew fault |
| [20261108T085152-4377034f](../runs/20261108T085152-4377034f/episode.md) | Dream-only | 913 | 31.35 | failed: Camera/state skew fault |
| [20261108T085325-48c1d092](../runs/20261108T085325-48c1d092/episode.md) | Dream-only | 2391 | 76.95 | unverified: Stopped by operator |
| [20261108T085622-a4285901](../runs/20261108T085622-a4285901/episode.md) | Dream-only | 2902 | 84.25 | unverified: Stopped by operator |
| [20261108T090009-11f46560](../runs/20261108T090009-11f46560/episode.md) | Dream-only | 855 | 28.95 | failed: Camera/state skew fault |
| [20261108T090131-ea2d3c5f](../runs/20261108T090131-ea2d3c5f/episode.md) | Dream-only | 654 | 21.6 | unverified: Stopped by operator |
| [20261108T090300-aa5e216a](../runs/20261108T090300-aa5e216a/episode.md) | Dream-only | 995 | 33.7 | failed: Camera/state skew fault |
| [20261108T090435-bab3d4fa](../runs/20261108T090435-bab3d4fa/episode.md) | Dream-only | 917 | 31.4 | failed: Camera/state skew fault |
| [20261108T090606-249041f1](../runs/20261108T090606-249041f1/episode.md) | Dream-only | 1017 | 36.0 | unverified: Stopped by operator |
| [20261108T090743-7838ce24](../runs/20261108T090743-7838ce24/episode.md) | Dream-only | 1113 | 38.9 | unverified: Stopped by operator |
| [20261108T091011-06666842](../runs/20261108T091011-06666842/episode.md) | Dream-only | 2640 | 81.25 | unverified: Stopped by operator |
| [20261108T091412-da7d7750](../runs/20261108T091412-da7d7750/episode.md) | Dream-only | 882 | 29.25 | failed: Camera/state skew fault |
| [20261108T091551-866474ad](../runs/20261108T091551-866474ad/episode.md) | Dream-only | 992 | 33.6 | failed: Camera/state skew fault |
| [20261108T091931-4693b1ef](../runs/20261108T091931-4693b1ef/episode.md) | Dream-only | 2073 | 59.85 | unverified: Stopped by operator |
| [20261108T092215-5152fc1a](../runs/20261108T092215-5152fc1a/episode.md) | Dream-only | 916 | 31.5 | failed: Camera/state skew fault |
| [20261108T092441-8b81b36c](../runs/20261108T092441-8b81b36c/episode.md) | Dream-only | 307 | 10.3 | unverified: Stopped by operator |
| [20261108T092532-b805f5dc](../runs/20261108T092532-b805f5dc/episode.md) | Dream-only | 1050 | 31.35 | unverified: Stopped by operator |
| [20261108T092747-a9855de6](../runs/20261108T092747-a9855de6/episode.md) | Dream-only | 826 | 27.4 | unverified: Stopped by operator |
| [20261108T092914-176e221b](../runs/20261108T092914-176e221b/episode.md) | Dream-only | 1039 | 35.65 | unverified: Stopped by operator |
| [20261108T093142-ba73de45](../runs/20261108T093142-ba73de45/episode.md) | Dream-only | 869 | 28.95 | failed: Camera/state skew fault |
| [20261108T093953-301cbd4a](../runs/20261108T093953-301cbd4a/episode.md) | Dream-only | 354 | 12.0 | unverified: Stopped by operator |
| [20261108T094150-0f525aa5](../runs/20261108T094150-0f525aa5/episode.md) | Dream-only | 958 | 33.8 | failed: Shutdown reported 1 error(s) |
| [20261108T095731-65b11757](../runs/20261108T095731-65b11757/episode.md) | Dream-only | 1004 | 33.9 | failed: Camera/state skew fault |
| [20261108T095907-f9306a9d](../runs/20261108T095907-f9306a9d/episode.md) | Dream-only | 866 | 29.2 | failed: Camera/state skew fault |
| [20261108T100033-accfc7b3](../runs/20261108T100033-accfc7b3/episode.md) | Dream-only | 508 | 16.8 | unverified: Stopped by operator |
| [20261108T100141-9547c1df](../runs/20261108T100141-9547c1df/episode.md) | Dream-only | 2366 | 62.6 | unverified: Stopped by operator |
| [20261108T100436-2688a7d8](../runs/20261108T100436-2688a7d8/episode.md) | Dream-only | 692 | 23.0 | unverified: Stopped by operator |
| [20261108T100552-6049af7e](../runs/20261108T100552-6049af7e/episode.md) | Dream-only | 2019 | 48.1 | unverified: Stopped by operator |
| [20261108T100830-1c661cb6](../runs/20261108T100830-1c661cb6/episode.md) | Dream-only | 1471 | 52.15 | unverified: Stopped by operator |
| [20261108T101035-5517bdc9](../runs/20261108T101035-5517bdc9/episode.md) | Dream-only | 826 | 29.0 | failed: Camera/state skew fault |
| [20261108T102900-c9e7a3ae](../runs/20261108T102900-c9e7a3ae/episode.md) | Dream-only | 737 | 24.4 | failed: Camera/state skew fault |
| [20261108T103021-0513c7ab](../runs/20261108T103021-0513c7ab/episode.md) | Dream-only | 760 | 24.0 | unverified: Stopped by operator |
| [20261108T103146-89e92ac2](../runs/20261108T103146-89e92ac2/episode.md) | Dream-only | 923 | 28.95 | unverified: Stopped by operator |
| [20261108T103324-1ca4f959](../runs/20261108T103324-1ca4f959/episode.md) | Dream-only | 501 | 16.8 | unverified: Stopped by operator |
| [20261108T103432-1c769494](../runs/20261108T103432-1c769494/episode.md) | Dream-only | 2037 | 56.6 | unverified: Stopped by operator |
| [20261108T103711-2ff0d474](../runs/20261108T103711-2ff0d474/episode.md) | Dream-only | 872 | 28.95 | failed: Camera/state skew fault |
| [20261108T103842-396674e6](../runs/20261108T103842-396674e6/episode.md) | Dream-only | 674 | 21.75 | failed: Camera/state skew fault |
| [20261108T111232-2d431273](../runs/20261108T111232-2d431273/episode.md) | Dream-only | 618 | 20.7 | unverified: Stopped by operator |
| [20261108T111355-36b14406](../runs/20261108T111355-36b14406/episode.md) | Dream-only | 460 | 15.3 | unverified: Stopped by operator |
| [20261108T111524-f14d6508](../runs/20261108T111524-f14d6508/episode.md) | Dream-only | 722 | 24.0 | unverified: Stopped by operator |
| [20261108T111737-090e9dba](../runs/20261108T111737-090e9dba/episode.md) | Dream-only | 993 | 33.8 | unverified: Stopped by operator |
| [20261108T111950-a9505e49](../runs/20261108T111950-a9505e49/episode.md) | Dream-only | 2162 | 63.0 | unverified: Stopped by operator |
| [20261108T112634-10c2df74](../runs/20261108T112634-10c2df74/episode.md) | Dream-only | 3032 | 96.15 | unverified: Stopped by operator |
| [20261108T113031-830dd1ed](../runs/20261108T113031-830dd1ed/episode.md) | Dream-only | 906 | 31.35 | failed: Camera/state skew fault |
| [20261108T113233-9f716dfd](../runs/20261108T113233-9f716dfd/episode.md) | Dream-only | 1404 | 26.7 | unverified: Stopped by operator |
| [20261108T113432-c3b5e276](../runs/20261108T113432-c3b5e276/episode.md) | Dream-only | 2093 | 31.35 | unverified: Hold timeout |
| [20261108T113938-fad1dcf5](../runs/20261108T113938-fad1dcf5/episode.md) | Dream-only | 719 | 24.35 | unverified: Stopped by operator |
| [20261108T114243-ae27b67d](../runs/20261108T114243-ae27b67d/episode.md) | Dream-only | 776 | 26.55 | failed: Camera/state skew fault |
| [20261108T114420-24289ff7](../runs/20261108T114420-24289ff7/episode.md) | Dream-only | 2059 | 71.3 | unverified: Stopped by operator |
| [20261108T114854-b4f5015d](../runs/20261108T114854-b4f5015d/episode.md) | Dream-only | 1448 | 50.4 | unverified: Stopped by operator |
| [20261108T115057-401fd33f](../runs/20261108T115057-401fd33f/episode.md) | Dream-only | 571 | 20.2 | unverified: Stopped by operator |
| [20261108T115207-034d8c9d](../runs/20261108T115207-034d8c9d/episode.md) | Dream-only | 1009 | 33.75 | failed: Camera/state skew fault |
| [20261108T115345-8533a4de](../runs/20261108T115345-8533a4de/episode.md) | Dream-only | 833 | 28.9 | unverified: Stopped by operator |
| [20261108T115511-a4d40468](../runs/20261108T115511-a4d40468/episode.md) | Dream-only | 432 | 14.65 | unverified: Stopped by operator |
| [20261108T115614-f7831f00](../runs/20261108T115614-f7831f00/episode.md) | Dream-only | 949 | 31.65 | failed: Camera/state skew fault |
| [20261108T115839-95da8784](../runs/20261108T115839-95da8784/episode.md) | Dream-only | 949 | 31.5 | failed: Camera/state skew fault |
| [20261108T120106-94fae308](../runs/20261108T120106-94fae308/episode.md) | Dream-only | 614 | 20.55 | unverified: Stopped by operator |
| [20261108T120217-ae0cdf86](../runs/20261108T120217-ae0cdf86/episode.md) | Dream-only | 861 | 28.8 | failed: Camera/state skew fault |
| [20261108T120344-0c2eb4c0](../runs/20261108T120344-0c2eb4c0/episode.md) | Dream-only | 914 | 26.85 | unverified: Stopped by operator |
| [20261108T120515-a6e21ca2](../runs/20261108T120515-a6e21ca2/episode.md) | Dream-only | 940 | 31.6 | failed: Camera/state skew fault |
| [20261108T120648-7996f774](../runs/20261108T120648-7996f774/episode.md) | Dream-only | 863 | 29.0 | failed: Camera/state skew fault |
| [20261108T120815-6b4e441f](../runs/20261108T120815-6b4e441f/episode.md) | Dream-only | 504 | 16.8 | unverified: Stopped by operator |
| [20261108T120921-ab1d54fb](../runs/20261108T120921-ab1d54fb/episode.md) | Dream-only | 798 | 26.75 | failed: Camera/state skew fault |
| [20261108T121902-e41b3a01](../runs/20261108T121902-e41b3a01/episode.md) | Dream-only | 527 | 17.95 | unverified: Stopped by operator |
| [20261108T122025-15878dc6](../runs/20261108T122025-15878dc6/episode.md) | Dream-only | 1668 | 61.9 | unverified: Stopped by operator |
| [20261108T122300-c52b18b9](../runs/20261108T122300-c52b18b9/episode.md) | Dream-only | 1044 | 38.3 | unverified: Stopped by operator |
| [20261108T122607-51caae26](../runs/20261108T122607-51caae26/episode.md) | Dream-only | 1123 | 41.05 | unverified: Stopped by operator |
| [20261108T122936-a104977c](../runs/20261108T122936-a104977c/episode.md) | Dream-only | 557 | 19.2 | unverified: Stopped by operator |
| [20261108T123049-206fc393](../runs/20261108T123049-206fc393/episode.md) | Dream-only | 475 | 16.45 | unverified: Stopped by operator |
| [20261108T123154-123ca6ff](../runs/20261108T123154-123ca6ff/episode.md) | Dream-only | 1440 | 53.4 | unverified: Stopped by operator |
| [20261108T123417-d820e953](../runs/20261108T123417-d820e953/episode.md) | Dream-only | 513 | 18.15 | unverified: Stopped by operator |
| [20261108T123531-2e0fbf08](../runs/20261108T123531-2e0fbf08/episode.md) | Dream-only | 489 | 16.8 | unverified: Stopped by operator |
| [20261108T123641-3c9d07b1](../runs/20261108T123641-3c9d07b1/episode.md) | Dream-only | 982 | 36.0 | unverified: Stopped by operator |

## Supporting investigations

- [Native feedback parser](feedback-2026-11-07.md)
- [Local timing and recording isolation](timing-2026-11-08.md)
- [Operating and recovery behavior](operations.md)

No aggregate success rate is computed: tasks, prompts, controller settings, objects and intervention policies changed across runs.
