import logging
import socket
import time
from urllib.request import urlopen

import numpy as np

from spill.config import Settings
from spill.control import Control
from spill.robot import make_rig
from spill.types import ARMS, ActionChunk
from spill.viewer import IncompleteHandshakeFilter, Viewer


def test_viser_invalidated_chunk_removes_all_trajectory_handles():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    c = Control()
    viewer = Viewer(make_rig(Settings()), c, port=port, hz=15)
    try:
        with urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            assert response.status == 200
            assert b"html" in response.read().lower()
        chunk = ActionChunk(
            1, 0, time.monotonic(), 20, {n: np.tile([0, 1, 1, 0, 0, 0, 1.0], (3, 1)) for n in ARMS}
        )
        viewer.publish(chunk=chunk, chunk_status="accepted")
        deadline = time.monotonic() + 3
        while (
            viewer.server.scene.get_handle_by_name("/accepted/left") is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert not viewer.error
        assert viewer.server.scene.get_handle_by_name("/accepted/left") is not None
        c.pause()
        deadline = time.monotonic() + 2
        while (
            viewer.server.scene.get_handle_by_name("/accepted/left") is not None
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert viewer.server.scene.get_handle_by_name("/accepted/left") is None
        assert not viewer.error
    finally:
        viewer.close()


def test_incomplete_handshake_reported_once_other_errors_preserved():
    from websockets.exceptions import InvalidMessage

    filt = IncompleteHandshakeFilter()
    error = InvalidMessage("did not receive a valid HTTP request")
    error.__cause__ = EOFError("connection closed while reading HTTP request line")

    def record(exc):
        return logging.LogRecord(
            "websockets.server",
            logging.ERROR,
            __file__,
            1,
            "opening handshake failed",
            (),
            (type(exc), exc, None),
        )

    first = record(error)
    assert filt.filter(first)
    assert first.exc_info is None
    assert "complete HTTP request" in first.getMessage()
    assert not filt.filter(record(error))
    other = record(RuntimeError("server failure"))
    assert filt.filter(other)
    assert other.exc_info is not None
