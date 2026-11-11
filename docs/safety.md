# Karma safety parity

Spill imports the installed local Karma implementation. It does not fork the
native controller or implement a competing motor loop. Read this table together
with `../src/openpi_control/cli.py` in the Karma checkout (from this document,
that is `../../src/openpi_control/cli.py`).

| Existing Karma behavior | Spill integration | Verification |
|---|---|---|
| `preflight_rig`, `doctor` | Run before energizing hardware; expose doctor and operator CLI passthrough | Static preflight; no live motors exercised |
| Camera discovery/probe | Serial-specific RealSense service, read-only `doctor --cameras` | Missing/frozen/skewed views rejected in tests |
| `power_up`, atomic session connect | Same startup function; partial failure closes the session | Uses Karma's established rollback path |
| `power_down`, native `MOVE_TO_READY_AND_SHUTDOWN` | Ctrl+C and Home & Stop invoke the same function | Failure on one arm and interrupted parking tests |
| Second Ctrl+C during park | KeyboardInterrupt reaches Karma's shutdown handler | Session cleanup verified |
| `--no-park` | Passed to shutdown selection | Stop/park flag tests |
| Capability fallback | Karma reports unsupported ready moves and closes in place | No invented home trajectory |
| `FollowerArm.command` / native limits | Sole execution route | No raw CAN writes in Spill |
| `StateGuard` | Used by KarmaRobot plus observation freshness checks | Stale/future/nonfinite telemetry tests |
| Hold | Spill commands measured joint pose plus last commanded grip | Preserve squeeze despite measured jaw deflection |
| Native heartbeat and process liveness | Native backend unchanged | Not replaced by cloud or Viser heartbeats |
| Native hardware fault/recovery policy | Native backend unchanged | Spill does not clear faults or restart a failed node |
| Factory motor timeout | Unchanged | No firmware timeout writes |
| Torque protective mode | Existing Karma default remains unchanged | No claim that the optional mode is enabled |
| Gravity compensation/float and drift guard | Original operator CLI and Karma APIs remain available | Not exposed to Astra; unavailable during autonomous ownership |
| Torque rescale, firmware zeros, ready/home configuration | Original operator maintenance interfaces | Never modified automatically by Spill |
| Gripper diagnostic data | Numeric measured/commanded openings in Viser | No fake moving gripper mesh |
| Native CAN ownership | Karma owns both buses | No Dream station or second driver is started |

Additional local checks: action shape/units/finite values, joint speed and
acceleration, gripper speed, command tracking, temperature, static obstacle/table
clearance, self/inter-arm capsules and sampled swept paths. Guards reject a bad
chunk. Recoverable rejection can request a bounded replan; a hardware fault stops
in place. Resume cannot resurrect a stale request.

Policy predictions are adapted before execution: gripper outputs saturate to
0..1, joint goals saturate to Karma's URDF limits, and each command approaches
its goal within configured speed, acceleration and gripper speed bounds. Discrete
braking limits prevent approaching a joint boundary faster than the trajectory
can stop; each chunk ends at zero commanded joint velocity for synchronous hold.
Cadence and horizon are unchanged, so bounded targets may not be fully reached.
The adapted chunk still passes all enabled trajectory checks. Both raw predictions
and accepted commands are logged. Nonfinite actions are never repaired.

The default maximum prediction age is 10 seconds, measured from its original
observation (not reset when a response arrives). This accommodates the observed
4.1–4.5 second synchronous Dream latency. Live camera/state freshness remains
0.25 seconds; live tracking checks and generation invalidation remain active.
A prediction is still based on an older scene: do not rearrange the workspace
while inference is in flight; pause and reobserve after changes.

With explicit `--zero-shot`, measured calibration and its verification flags are
not required. Static obstacle/table clearance, self/inter-arm capsules and swept
collision checks are disabled. All non-geometric checks and Karma shutdown
behavior remain enabled. Viser uses nominal base placement and labels this mode;
the rendered geometry is not a measured collision map. No placeholder calibration
is silently accepted, and no flags are marked verified on the operator's behalf.

Stop controls have different physical outcomes. Pause holds; home-and-stop moves
the arms and then removes power; Stop Now removes power in place. A loaded cup
may remain in the gripper during a home move; arrange a clear home path and account
for the loss of holding power on shutdown. No software button replaces the physical
emergency stop.

Hardware/camera failures that end a run use Karma's home-and-shutdown path. Native firmware/controller fault behavior remains authoritative. The Python
collision guard is for policy actions; Karma's native parking path retains its own
behavior and does not run through Spill's trajectory validator.

Feedback gap handling uses a persistent Karma `StateGuard` and its `MAX_STALE_S`
(one second). At the 250 ms freshness limit, Spill inhibits new commands, clears
the observation, invalidates queued predictions, and leaves native control at its
existing target. It does not generate a hold/home command from stale measurements.
Fresh feedback triggers a new observation and replan; an old chunk cannot resume.
A fault that ends the run (per-motor feedback one second old, tracking, temperature,
camera, observation or planner exceptions) no longer de-energizes in place. Spill
requests Karma's home-and-shutdown path, as `karma infer` does; the native node homes
with its own motor feedback. `--no-park`, a second Ctrl+C and Stop Now still stop in
place. Native watchdogs are not disabled or extended.
This avoids treating every brief gap as a terminal fault; it does not repair a
motor, CAN wiring, or driver problem. Camera failures remain terminal.

Validated offline: brief-gap command inhibition, recovered-state replanning,
sustained-gap shutdown, cancellation during a gap, cloud-wait cancellation,
home/stop selection, trajectory guards and LeRobot v3 output. This is preservation
of applicable Karma protections, not a claim that every optional Karma feature is
enabled. Zero-shot mode still has no calibrated geometric collision checking.

Viser callbacks only request control transitions. The local supervisor serializes
command authorization under the same lock as pause/stop/generation changes.
API workers are daemon threads; shutdown does not join a blocked cloud request.
The log writer and renderer are outside command execution. A log backlog fails
the run instead of silently losing the action audit.

The parity promise is preservation of applicable YAM mechanisms, not that every
Karma calibration command is safe in every scene or that hardware has been tested.
