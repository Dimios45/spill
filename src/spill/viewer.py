from __future__ import annotations

import logging
import os
import signal
import threading
import time

import numpy as np

from .types import ARMS, CAMERAS


class IncompleteHandshakeFilter(logging.Filter):
    """Report abandoned HTTP connections once, preserving other server errors."""

    def __init__(self):
        super().__init__()
        self.reported = False

    def filter(self, record):
        from websockets.exceptions import InvalidMessage

        exc = record.exc_info[1] if record.exc_info else None
        if (
            record.getMessage() != "opening handshake failed"
            or not isinstance(exc, InvalidMessage)
            or not isinstance(exc.__cause__, EOFError)
        ):
            return True
        if self.reported:
            return False
        self.reported = True
        record.msg = (
            "Viser: a client disconnected before sending a complete HTTP request. "
            "Use http://<robot-host-ip>:8080 (not HTTPS). "
            "Repeated incomplete connections will be omitted."
        )
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.levelno = logging.WARNING
        record.levelname = "WARNING"
        return True


class Viewer:
    """Latest-state mailbox: rendering never runs in the execution thread."""

    def __init__(self, rig, control, *, port=8080, hz=8, enabled=True, uncalibrated=False):
        self.control, self.hz, self.enabled = control, hz, enabled
        self.lock = threading.Lock()
        self.data = {}
        self.stop_event = threading.Event()
        self.error = ""
        self.thread = None
        self.scene = None
        if not enabled:
            return
        import viser
        from openpi_control.viz import ArmSceneVisualizer, ArmSpec

        logger = logging.getLogger("websockets.server")
        if not any(isinstance(f, IncompleteHandshakeFilter) for f in logger.filters):
            logger.addFilter(IncompleteHandshakeFilter())
        # Listen on the LAN so the operator can use another laptop.
        self.server = viser.ViserServer(host="0.0.0.0", port=port)
        self.scene = ArmSceneVisualizer.from_rig(rig, server=self.server)
        self.ghost = ArmSceneVisualizer(
            {
                "prediction_" + a.name: ArmSpec(
                    a.model,
                    effector_model=a.effector_model,
                    instance_config=a.instance_config,
                    base_position=a.base_position,
                    base_rotation_wxyz=a.base_rotation_wxyz,
                    color=(130, 160, 180),
                )
                for a in rig.arms
            },
            server=self.server,
            show_grid=False,
            show_labels=True,
        )
        self.info = self.server.gui.add_markdown("Starting Spill…")
        if uncalibrated:
            self.server.gui.add_markdown(
                "**Zero-shot mode:** geometric collision checks are off. "
                "Arm placement uses nominal rig geometry; trajectories are illustrative. "
                "Joint/motion limits and telemetry guards remain active."
            )
        self.grip = self.server.gui.add_markdown("Grippers: awaiting feedback")
        with self.server.gui.add_folder("Operator controls"):
            self.server.gui.add_button("Pause / Hold").on_click(lambda _: control.pause())
            self.server.gui.add_button("Resume (reobserve)").on_click(lambda _: control.resume())
            self.server.gui.add_button("Home & Stop").on_click(lambda _: control.stop(park=True))
            self.server.gui.add_button("Stop Now — de-energize in place", color="red").on_click(
                self._stop_now
            )
        self.images = {}
        for group in ("Live cameras", "Astra input", "Dream input"):
            with self.server.gui.add_folder(group):
                for role in CAMERAS:
                    self.images[group, role] = self.server.gui.add_image(
                        np.zeros((176, 320, 3), np.uint8), label=role
                    )
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        print(
            f"Viser listening on 0.0.0.0:{self.server.get_port()} "
            f"— open http://<robot-host-ip>:{self.server.get_port()}"
        )

    def _stop_now(self, _):
        self.control.stop(park=False, reason="Viser Stop Now")
        if self.control.parking:
            os.kill(os.getpid(), signal.SIGINT)

    def publish(self, **data):
        with self.lock:
            self.data.update(data)

    def _loop(self):
        from PIL import Image

        previous_chunk = None
        previous_status = None
        line_handles = []
        while not self.stop_event.is_set():
            with self.lock:
                data = dict(self.data)
            try:
                obs = data.get("observation")
                if obs:
                    for n in ARMS:
                        self.scene.update(n, obs.joints[n][:6])
                    for role in CAMERAS:
                        self.images["Live cameras", role].image = np.asarray(
                            Image.fromarray(obs.frames[role].rgb).resize((424, 240))
                        )
                    commanded = data.get("commanded", obs.joints)
                    self.grip.content = "Gripper opening (1=open): " + " | ".join(
                        f"{n}: measured {obs.joints[n][-1]:.3f}, commanded {commanded[n][-1]:.3f}"
                        for n in ARMS
                    )
                for purpose, group in (
                    ("astra_observation", "Astra input"),
                    ("dream_observation", "Dream input"),
                ):
                    snapshot = data.get(purpose)
                    if snapshot:
                        for role in CAMERAS:
                            size = (320, 176) if group == "Dream input" else (424, 240)
                            self.images[group, role].image = np.asarray(
                                Image.fromarray(snapshot.frames[role].rgb).resize(size)
                            )
                chunk = data.get("chunk")
                invalid = (
                    self.control.paused
                    or self.control.stopping
                    or (chunk and chunk.generation != self.control.generation)
                )
                if invalid:
                    chunk = None
                status = data.get("chunk_status", "accepted")
                if chunk is not previous_chunk or status != previous_status:
                    self.scene.clear_chunk()
                    for handle in line_handles:
                        handle.remove()
                    line_handles.clear()
                    if chunk:
                        self.scene.update_chunk(chunk.arms)
                        for n in ARMS:
                            # FK only in this renderer, with Karma's URDF convention.
                            points = np.array(
                                [
                                    self.scene[n].world_end_effector_position(q[:6])
                                    for q in chunk.arms[n]
                                ],
                                dtype=np.float32,
                            )
                            if len(points) > 1:
                                color = (240, 70, 70) if status == "rejected" else (70, 230, 120)
                                line_handles.append(
                                    self.server.scene.add_line_segments(
                                        f"/{status}/{n}",
                                        points=np.stack([points[:-1], points[1:]], axis=1),
                                        colors=color,
                                        thickness=2,
                                        thickness_units="screen",
                                    )
                                )
                            self.ghost.update("prediction_" + n, chunk.arms[n][-1, :6])
                    previous_chunk = chunk
                    previous_status = status
                for n in ARMS:
                    self.ghost[
                        n if n.startswith("prediction_") else "prediction_" + n
                    ].base_frame.visible = chunk is not None
                self.scene.set_chunk_progress(data.get("row", 0))
                decision = data.get("decision")
                description = ""
                if decision:
                    description = (
                        f"\n\n**Active subtask:** {decision.active_subtask}\n\n"
                        + "\n".join(f"- {s}" for s in decision.subtasks)
                        + f"\n\n{decision.explanation}\n\nEvidence: {decision.evidence}"
                    )
                age = f"{time.monotonic() - obs.timestamp:.3f}s" if obs else "unknown"
                self.info.content = (
                    f"**{data.get('status', 'Starting')}** — {data.get('prompt', '')}\n\n"
                    f"Observation age: {age}; predicted horizon: {chunk.length if chunk else 0} rows; "
                    f"row: {data.get('row', 0)}; recoveries: {data.get('recoveries', 0)}\n\n"
                    f"{self.control.reason}\n\n{data.get('detail', '')}" + description
                )
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"
                # UI failure cannot interfere with the command watchdog or stop handler.
            self.stop_event.wait(1 / self.hz)

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        if self.scene:
            self.server.stop()
