from __future__ import annotations

import dataclasses
import threading
import time

from openpi_control.safety import MAX_STALE_S

from .types import (
    ARMS,
    ExecutionReport,
    FeedbackGap,
    Observation,
    ObservationSkewError,
    RunResult,
    SafetyError,
)


class Job:
    """Single in-flight daemon job; hardware shutdown never joins network requests."""

    def __init__(self):
        self.thread = None
        self.result = None
        self.error = None
        self.done = threading.Event()
        self.generation = -1
        self.started = 0.0
        self.executed_at_submit = 0

    @property
    def pending(self):
        return self.thread is not None

    def submit(self, generation, function, *args):
        if self.pending:
            raise RuntimeError("Only one request may be in flight")
        self.generation = generation
        self.started = time.monotonic()
        self.result = self.error = None
        self.done.clear()

        def run():
            try:
                self.result = function(*args)
            except Exception as exc:
                self.error = exc
            finally:
                self.done.set()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def take(self):
        if not self.pending or not self.done.is_set():
            return None
        result = (self.generation, self.result, self.error)
        self.thread = None
        return result


class Runner:
    def __init__(
        self,
        settings,
        control,
        robot,
        cameras,
        planner,
        policy,
        guard,
        recorder,
        viewer,
        *,
        hardware=False,
    ):
        self.settings, self.control, self.robot, self.cameras = settings, control, robot, cameras
        self.planner, self.policy, self.guard, self.recorder, self.viewer = (
            planner,
            policy,
            guard,
            recorder,
            viewer,
        )
        self.hardware = hardware
        self.observation_id = 0
        self.observation = None
        self.obs_lock = threading.Lock()
        self.observe_stop = threading.Event()
        self.observe_error = None
        self.feedback_gap = None
        self.feed_enabled = threading.Event()
        self.observer = None
        self.plan_job, self.motion_job = Job(), Job()
        self.commanded = None
        self.history = []
        self.planner_name = getattr(planner, "display_name", "Astra")
        self.policy_name = getattr(policy, "display_name", "Dream")
        self.report = ExecutionReport()

    def _capture_observation(self):
        # A scheduling pause between reading state and taking the camera mailbox
        # can create an inconsistent snapshot even when every producer is healthy.
        # Discard that acquisition, invalidate actions, and retry once. Never
        # change source timestamps or publish the discarded observation.
        for attempt in range(2):
            started = time.monotonic()
            q, times = self.robot.read()
            frames = self.cameras.latest()
            elapsed = time.monotonic() - started
            if elapsed > self.settings.limits.camera_skew_s:
                self.recorder.event(
                    "observation_acquisition_delayed", attempt=attempt + 1,
                    elapsed_s=elapsed, state_times=times,
                    camera_times={n: f.captured_at for n, f in frames.items()},
                )
                if attempt:
                    raise SafetyError("Observation acquisition delayed twice; cannot obtain coherent snapshot")
                with self.control.lock:
                    self.feed_enabled.clear()
                    self.control.pause("Observation acquisition delayed; discarding snapshot and reacquiring")
                continue
            return Observation(
                self.observation_id, self.control.generation,
                min(f.captured_at for f in frames.values()), frames, q, times,
            )

    def _observe(self):
        candidate = None
        try:
            while not self.observe_stop.is_set():
                # State reads do not command motors. Capture owns camera streams independently.
                try:
                    obs = self._capture_observation()
                except FeedbackGap as exc:
                    self._begin_feedback_gap(exc)
                    if time.monotonic() - self.feedback_gap >= MAX_STALE_S:
                        raise SafetyError(
                            "Feedback did not recover within one-second grace"
                        ) from exc
                    self.viewer.publish(status="Waiting for fresh motor feedback", chunk=None)
                    self.observe_stop.wait(0.01)
                    continue
                candidate = obs
                obs.validate(self.settings.limits.state_age_s, self.settings.limits.camera_skew_s)
                self.observation_id += 1
                with self.obs_lock:
                    self.observation = obs
                if self.feedback_gap is not None:
                    self.recorder.event(
                        "feedback_recovered", gap_s=time.monotonic() - self.feedback_gap
                    )
                    self.feedback_gap = None
                    print("Motor feedback recovered; reobserving and replanning", flush=True)
                self.viewer.publish(observation=obs)
                if getattr(self.recorder, "dataset_enabled", False) and self.commanded is not None:
                    self.recorder.observation(obs, purpose="dataset")
                    self.recorder.event(
                        "dataset_sample",
                        observation_id=obs.id,
                        sampled_at=time.monotonic(),
                        arms={n: q.copy() for n, q in self.commanded.items()},
                    )
                if self.feed_enabled.is_set() and self.control.permits(obs.generation):
                    self.policy.feed(obs)
                self.observe_stop.wait(1 / 30)
        except Exception as exc:
            self.observe_error = exc
            try:
                self.recorder.event(
                    "observation_fault",
                    error_type=type(exc).__name__,
                    error=str(exc),
                    telemetry=list(getattr(self.robot, "telemetry_history", [])),
                    observation_timing=(
                        dict(
                            observation_id=candidate.id,
                            state_times=candidate.state_times,
                            frames={n: dict(captured_at=f.captured_at, sequence=f.sequence,
                                            device_timestamp_ms=f.device_timestamp_ms)
                                    for n, f in candidate.frames.items()},
                        ) if candidate is not None else None
                    ),
                )
            except Exception:
                pass  # A failed logger must not hide the hardware fault.

    def snapshot(self):
        if self.observe_error:
            if isinstance(self.observe_error, ObservationSkewError):
                raise self.observe_error
            raise SafetyError(f"Observation service failed: {self.observe_error}")
        if self.feedback_gap is not None:
            return None
        with self.obs_lock:
            obs = self.observation
        if obs is None:
            return None
        obs.validate(self.settings.limits.state_age_s, self.settings.limits.camera_skew_s)
        return obs

    def _begin_feedback_gap(self, exc):
        with self.control.lock:
            if self.feedback_gap is None:
                self.feedback_gap = time.monotonic()
                self.feed_enabled.clear()
                self.control.replan("Feedback gap: discard predictions and wait")
                self.recorder.event("feedback_gap", reason=str(exc))
                print(f"Feedback gap: {exc}; inhibiting new commands", flush=True)
            with self.obs_lock:
                self.observation = None

    def _hold_if_fresh(self):
        try:
            self.commanded = self.robot.hold()
            return True
        except FeedbackGap as exc:
            self._begin_feedback_gap(exc)
            return False

    def _invalidate(self):
        self.feed_enabled.clear()
        self.viewer.publish(chunk=None, row=0)
        self.guard.reset()
        return self._hold_if_fresh()

    def run(self, prompt):
        start = time.monotonic()
        outcome, reason = "unverified", "Stopped by operator"
        stage, seen_generation = "plan", self.control.generation
        chunk, row, next_tick = None, 0, 0.0
        step_started = 0.0
        recoveries = {}
        execution_recoveries = {}
        retry_after = 0.0
        observe_decisions = 0
        planner_failures = 0
        self.commanded, _ = self.robot.read()
        self.observer = threading.Thread(target=self._observe, daemon=True)
        self.observer.start()
        self.viewer.publish(prompt=prompt, status="Observing")
        try:
            while not self.control.stopping:
                now = time.monotonic()
                self.recorder.check()
                if now - start >= self.settings.limits.task_timeout_s:
                    reason = "Task time limit"
                    self.control.stop(reason="Task time limit")
                    break
                obs = self.snapshot()
                if obs is None:
                    if self.feedback_gap is not None:
                        time.sleep(0.005)
                        continue
                    if now - start > 2:
                        raise SafetyError("No observation after startup")
                    time.sleep(0.005)
                    continue
                if seen_generation != self.control.generation:
                    if not self._invalidate():
                        continue
                    seen_generation = self.control.generation
                    chunk, row, stage = None, 0, "plan"
                    observe_decisions = 0
                    self.recorder.event(
                        "control",
                        generation=seen_generation,
                        paused=self.control.paused,
                        reason=self.control.reason,
                    )
                    print(
                        f"{'Paused / holding' if self.control.paused else 'Replanning'}: "
                        f"{self.control.reason}",
                        flush=True,
                    )
                if self.control.paused:
                    self.viewer.publish(status="Paused / holding")
                    if now - self.control.pause_since >= self.settings.limits.hold_timeout_s:
                        reason = "Hold timeout"
                        self.control.stop(reason=reason)
                    # Consume stale completed results, never their actions.
                    self.plan_job.take()
                    self.motion_job.take()
                    time.sleep(0.01)
                    continue
                if obs.generation != self.control.generation:
                    time.sleep(0.005)
                    continue
                if not getattr(self.robot, "shadow", False):
                    for name in ARMS:
                        if (
                            max(abs(self.commanded[name][:6] - obs.joints[name][:6]))
                            > self.settings.limits.tracking_error
                        ):
                            raise SafetyError(f"{name} tracking error while supervising")
                if stage == "plan":
                    if now < retry_after:
                        self.viewer.publish(status="Holding during provider backoff")
                        time.sleep(0.01)
                        continue
                    # Do not reset a Dream session while a discarded network request is still running.
                    if self.motion_job.pending:
                        self.motion_job.take()
                        time.sleep(0.005)
                        continue
                    if not self.plan_job.pending:
                        self.viewer.publish(status="Astra planning", astra_observation=obs)
                        plan_started = time.monotonic()
                        print(f"{self.planner_name}: preparing task; arms holding", flush=True)
                        self.plan_job.submit(
                            obs.generation, self.planner.decide, prompt, obs, list(self.history)
                        )
                    item = self.plan_job.take()
                    if item:
                        generation, decision, error = item
                        if generation != self.control.generation:
                            continue
                        if error:
                            from .providers import planner_retryable

                            planner_failures += 1
                            if (
                                planner_retryable(error)
                                and planner_failures <= self.settings.planner_retries
                            ):
                                delay = self.settings.planner_retry_delay_s * planner_failures
                                retry_after = time.monotonic() + delay
                                self._hold_if_fresh()
                                self.guard.reset()
                                self.recorder.event(
                                    "planner_retry",
                                    attempt=planner_failures,
                                    delay_s=delay,
                                    error_type=type(error).__name__,
                                    generation=generation,
                                )
                                print(
                                    f"Astra {type(error).__name__}: holding; retry "
                                    f"{planner_failures}/{self.settings.planner_retries} "
                                    f"in {delay:g}s with fresh images",
                                    flush=True,
                                )
                                if type(error).__name__ == "ValidationError":
                                    print(
                                        "Astra returned malformed JSON; discarded the entire "
                                        "response. No motion will use partial instructions.",
                                        flush=True,
                                    )
                                continue
                            self.control.pause(f"Planner error: {type(error).__name__}: {error}")
                            continue
                        planner_failures = 0
                        self.viewer.publish(decision=decision)
                        self.recorder.event(
                            "decision", generation=generation, **decision.model_dump()
                        )
                        print(
                            f"{self.planner_name} [{decision.action}] in {time.monotonic() - plan_started:.1f}s: "
                            f"{decision.active_subtask}\n"
                            f"  Reason: {decision.explanation}\n"
                            f"  Evidence: {decision.evidence}\n"
                            f"  Instruction: {decision.instruction}",
                            flush=True,
                        )
                        if decision.action == "finish":
                            outcome = (
                                decision.outcome
                                if decision.outcome != "in_progress"
                                else "unverified"
                            )
                            reason = decision.evidence
                            self.control.stop(reason="Task complete: " + reason)
                            break
                        if decision.action == "pause":
                            self.control.pause(decision.explanation)
                            continue
                        if decision.action == "observe":
                            observe_decisions += 1
                            self.history.append(dict(
                                action="observe", consecutive_observations=observe_decisions,
                                explanation=decision.explanation, evidence=decision.evidence,
                                instruction=decision.instruction,
                                motion_executed=False,
                            ))
                            self.recorder.event(
                                "observation_wait", count=observe_decisions, limit=3,
                                generation=generation, explanation=decision.explanation,
                                evidence=decision.evidence, motion_executed=False,
                            )
                            print(
                                f"Inspection {observe_decisions}/3: fresh images only; "
                                "no Dream motion or camera repositioning",
                                flush=True,
                            )
                            if observe_decisions >= 3:
                                self.control.pause(
                                    "Three observations without action. Astra: "
                                    + decision.explanation + " Evidence: " + decision.evidence
                                )
                            continue
                        observe_decisions = 0
                        key = decision.active_subtask.strip().lower()
                        if decision.recovery:
                            recoveries[key] = recoveries.get(key, 0) + 1
                            print(
                                f"Recovery attempt {recoveries[key]}/"
                                f"{self.settings.limits.retries_per_subtask}: {key}",
                                flush=True,
                            )
                        if recoveries.get(key, 0) > self.settings.limits.retries_per_subtask:
                            self.control.pause("Recovery budget exhausted")
                            continue
                        self.feed_enabled.clear()
                        motion_budget = (
                            self.settings.execution_window_s
                            if self.settings.execution_window_s is not None
                            else decision.duration_s
                        )
                        if decision.recovery:
                            motion_budget = self.settings.recovery_window_s
                        if getattr(self.policy, "single_step", False):
                            motion_budget = decision.duration_s
                        self.recorder.event(
                            "execution_window", requested_s=decision.duration_s,
                            effective_s=motion_budget, generation=generation,
                            recovery=decision.recovery,
                            completion="whole_chunk",
                        )
                        print(
                            f"{self.policy_name} {'recovery' if decision.recovery else 'execution'} window: "
                            f"{motion_budget:g}s commanded motion "
                            f"before {self.planner_name} review (finish current chunk)", flush=True,
                        )
                        # Reset can make a short network call; put it in the motion worker.
                        self.motion_job.submit(
                            generation, self._reset_policy, decision.instruction, generation, obs
                        )
                        stage = "reset"
                        self.report = ExecutionReport()
                        step_started = now
                        self.viewer.publish(
                            status="Starting subtask", recoveries=sum(recoveries.values())
                        )
                elif stage == "reset":
                    item = self.motion_job.take()
                    if item:
                        generation, _, error = item
                        if generation != self.control.generation:
                            continue
                        if error:
                            self.control.pause(f"Policy reset error: {error}")
                            continue
                        self.feed_enabled.set()
                        stage = "execute"
                elif stage == "execute":
                    self.viewer.publish(status=f"{self.policy_name} executing", commanded=self.commanded)
                    budget_used = self.report.elapsed_s >= motion_budget - 1e-9
                    if budget_used and not self.motion_job.pending and chunk is None:
                        self.feed_enabled.clear()
                        if not self._hold_if_fresh():
                            continue
                        self.guard.reset()
                        self.report.wall_elapsed_s = now - step_started
                        self.recorder.event("subtask_report", **dataclasses.asdict(self.report))
                        print(
                            f"Subtask: {self.report.elapsed_s:.1f}s commanded motion, "
                            f"{self.report.policy_wait_s:.1f}s {self.policy_name} action preparation, "
                            f"{self.report.chunks} chunks; returning to {self.planner_name}",
                            flush=True,
                        )
                        self.history.append(
                            dict(
                                instruction=decision.instruction,
                                active_subtask=decision.active_subtask,
                                recovery=decision.recovery,
                                explanation=decision.explanation,
                                evidence=decision.evidence,
                                report=dataclasses.asdict(self.report),
                            )
                        )
                        if getattr(self.planner, "continuous", False):
                            # A reporting checkpoint is not a new Dream episode.
                            # Keep the policy session/history until operator replan.
                            self.report = ExecutionReport()
                            step_started = now
                            self.feed_enabled.set()
                            self.recorder.event("policy_session_continued", generation=obs.generation)
                            print("Dream-only checkpoint: continuing the same policy session", flush=True)
                            stage = "execute"
                        else:
                            stage = "plan"
                        continue
                    # At most one in flight; inference can overlap only the currently validated chunk.
                    remaining = 0 if chunk is None else chunk.length - row
                    if (
                        not budget_used
                        and not self.motion_job.pending
                        and self.policy.refill_due(row, remaining)
                    ):
                        self.motion_job.executed_at_submit = self.report.rows
                        print(
                            f"{self.policy_name} inference: {self.report.elapsed_s:.1f}/"
                            f"{motion_budget:g}s motion budget used",
                            flush=True,
                        )
                        self.viewer.publish(dream_observation=obs)
                        self.motion_job.submit(
                            obs.generation,
                            self.policy.infer,
                            obs,
                            {n: q.copy() for n, q in self.commanded.items()},
                        )
                    item = self.motion_job.take()
                    if item:
                        generation, new_chunk, error = item
                        if generation != self.control.generation:
                            continue
                        self.report.policy_wait_s += time.monotonic() - self.motion_job.started
                        if getattr(self.policy, "last_request", None) is not None:
                            self.viewer.publish(dream_observation=self.policy.last_request)
                        if error:
                            message = f"{self.policy_name} inference failed: {type(error).__name__}: {error}"
                            retryable = getattr(error, "retryable", False) or type(
                                error
                            ).__name__ in ("DreamTimeout", "DreamSessionExpired")
                            if retryable:
                                retry_after = now + max(
                                    1.0, float(getattr(error, "retry_after_s", None) or 1.0)
                                )
                                self._recover(message, decision.instruction, execution_recoveries)
                            else:
                                self.control.pause(message)
                            continue
                        # Drop only rows whose time actually elapsed in commanded motion during inference.
                        skipped = self.report.rows - self.motion_job.executed_at_submit
                        if skipped:
                            if skipped >= new_chunk.length:
                                self.control.pause("Prediction exhausted during inference")
                                continue
                            new_chunk = dataclasses.replace(
                                new_chunk, arms={n: a[skipped:] for n, a in new_chunk.arms.items()}
                            )
                        self.viewer.publish(chunk=new_chunk, chunk_status="raw")
                        try:
                            new_chunk = self.guard.prepare(new_chunk, self.commanded)
                        except SafetyError as exc:
                            print(f"Trajectory rejected: {exc}", flush=True)
                            self.viewer.publish(
                                chunk=new_chunk, chunk_status="rejected", detail=str(exc)
                            )
                            self.recorder.event("rejected", error=str(exc), arms=new_chunk.arms)
                            self._recover(
                                f"Trajectory rejected: {exc}",
                                decision.instruction,
                                execution_recoveries,
                            )
                            continue
                        now = time.monotonic()
                        chunk, row, next_tick = new_chunk, 0, now
                        self.report.chunks += 1
                        print(
                            f"{self.policy_name}: accepted {chunk.length} bounded rows at {chunk.hz:g} Hz; "
                            f"prediction age {now - chunk.requested_at:.2f}s",
                            flush=True,
                        )
                        self.recorder.event(
                            "accepted", arms=chunk.arms, hz=chunk.hz, generation=generation
                        )
                        self.viewer.publish(
                            chunk=chunk, chunk_status="accepted", detail=str(chunk.timing)
                        )
                    if chunk and now >= next_tick:
                        dt = 1 / chunk.hz
                        # Missed deadlines do not cause a catch-up burst.
                        if now - next_tick > max(0.1, 2 * dt):
                            self.recorder.event(
                                "execution_deadline_missed", late_s=now - next_tick,
                                limit_s=max(0.1, 2 * dt), row=row, hz=chunk.hz,
                                observation_id=obs.id, generation=self.control.generation,
                            )
                            self.control.pause(
                                f"Execution deadline missed: {(now - next_tick) * 1000:.1f}ms "
                                f"late; limit={max(0.1, 2 * dt) * 1000:g}ms"
                            )
                            continue
                        target = {n: chunk.arms[n][row] for n in ARMS}
                        with self.control.lock:
                            if self.control.permits(chunk.generation):
                                # Whole-chunk geometry validation can take time.
                                # Recheck the latest telemetry at dispatch, not just
                                # the snapshot taken at the start of this loop.
                                obs = self.snapshot()
                                if obs is None:
                                    raise SafetyError("Observation missing at command dispatch")
                                self.guard.step(target, self.commanded, obs.joints, dt)
                                self.robot.command(target)
                                self.commanded = {n: q.copy() for n, q in target.items()}
                                self.recorder.event(
                                    "command",
                                    observation_id=obs.id,
                                    generation=obs.generation,
                                    arms=target,
                                    hz=chunk.hz,
                                )
                                # Keep each command's measured observation available for dataset export.
                                self.recorder.observation(obs, purpose="execution")
                                row += 1
                                self.report.rows += 1
                                self.report.elapsed_s += dt
                                self.viewer.publish(row=row, commanded=self.commanded)
                        next_tick = now + dt
                        if row >= chunk.length:
                            chunk = None
                            self.guard.reset()
                time.sleep(0.005)
        except Exception as exc:
            outcome, reason = "failed", f"{type(exc).__name__}: {exc}"
            # A fault does not cancel homing: Karma's native node homes with its own
            # motor feedback. The operator's choice (--no-park, Stop Now) stays in force.
            self.control.stop(reason=reason)
        finally:
            self.feed_enabled.clear()
            self.observe_stop.set()
            if self.observer:
                self.observer.join(timeout=1)
            self.viewer.publish(
                status="Parking then shutdown" if self.control.park else "De-energizing", chunk=None
            )
            self.control.parking = True
            try:
                failures = self.robot.close(park=self.control.park)
                if failures:
                    outcome, reason = "failed", f"Shutdown reported {failures} error(s)"
            finally:
                self.control.parking = False
            result = RunResult(
                outcome, reason, time.monotonic() - start, self.hardware, self.control.interventions
            )
            self.recorder.event("result", **dataclasses.asdict(result))
            self.viewer.publish(status="Stopped", detail=reason)
        return result

    def _reset_policy(self, instruction, generation, obs):
        self.policy.reset(instruction, generation)
        # Reset may take a network round trip. Seed from fresh telemetry, never from
        # the observation that existed before that round trip.
        current = self.snapshot()
        if current is not None and current.generation == generation:
            self.policy.feed(current)

    def _recover(self, message, instruction, attempts):
        key = instruction.strip().lower()
        attempts[key] = attempts.get(key, 0) + 1
        self.report.error = message
        self.history.append(dict(instruction=instruction, report=dataclasses.asdict(self.report)))
        self.recorder.event("recovery", reason=message, attempt=attempts[key])
        # Also cap total fault recoveries, so renaming a subtask cannot evade the budget.
        if attempts[key] > self.settings.limits.retries_per_subtask or sum(attempts.values()) > 6:
            self.control.pause("Recovery budget exhausted: " + message)
        else:
            self.control.replan(message)
