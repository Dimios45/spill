"""Private local JSON-lines transport; the worker never opens robot hardware.

Stdout is exclusively the reply channel. SDK diagnostics go to stderr.
Credentials are inherited through the environment / supported credentials file.
"""

import contextlib
import dataclasses
import json
import sys

import numpy as np


def encode(value):
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def main():
    channel = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        import dream

        client = dream.DreamClient()
        for line in sys.stdin:
            try:
                request = json.loads(line)
                op, args = request["op"], request.get("args", {})
                if op == "policy":
                    result = client.policy(args["config"])
                elif op == "get_models":
                    result = client.get_models()
                elif op == "reset_episode":
                    result = client.reset_episode()
                elif op == "infer":
                    for tick in args["ticks"]:
                        state = {
                            k: np.asarray(v, dtype=np.float32) if k.startswith("state.") else v
                            for k, v in tick["state"].items()
                        }
                        client.set_observation(tick["frames"], state, timestamp=tick["timestamp"])
                    action = client.get_action(commanded=args["commanded"])
                    horizon = len(action["q_l_chunk"])
                    if not 1 <= horizon <= 256:
                        raise ValueError("Invalid action horizon")
                    result = dict(
                        action=action,
                        timing=client.last_timing,
                        mode=client.mode,
                        refill_table=[
                            [
                                client.refill_due(executed, remaining)
                                for remaining in range(horizon + 1)
                            ]
                            for executed in range(horizon + 1)
                        ],
                    )
                elif op == "refill_due":
                    result = client.refill_due(args["executed"], args["remaining"])
                elif op == "close":
                    client.close()
                    return
                else:
                    raise ValueError("Unsupported worker operation")
                reply = dict(ok=True, result=result)
            except Exception as exc:
                reply = dict(
                    ok=False,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    retryable=getattr(exc, "retryable", False),
                    retry_after_s=getattr(exc, "retry_after_s", None),
                )
            channel.write(json.dumps(reply, default=encode, allow_nan=False) + "\n")
            channel.flush()


if __name__ == "__main__":
    main()
