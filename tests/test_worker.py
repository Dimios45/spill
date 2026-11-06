import sys
import time

import pytest

from spill.dream_process import IsolatedDreamClient, RemoteDreamError
from spill.types import SpillError

STUB = """
import json,sys
for line in sys.stdin:
    req=json.loads(line); op=req['op']; args=req['args']
    if op=='policy': result=None
    elif op=='get_models': result=[{'id':'dreamlabs/dream-1','servable':True}]
    elif op=='reset_episode': result=None
    elif op=='infer':
        assert len(args['ticks'][0]['frames']['video.overhead'])>100000
        result={'action':{'q_l_chunk':[[0]*7], 'q_r_chunk':[[0]*7]},'timing':{'rtt_ms':10},'mode':'sync','refill_table':[[True,False],[True,False]]}
    else:
        print(json.dumps({'ok':False,'error_type':'DreamTimeout','error':'retry','retryable':True,'retry_after_s':1}),flush=True)
        continue
    print(json.dumps({'ok':True,'result':result}),flush=True)
"""


def test_isolated_transport_large_request_and_pacing(tmp_path):
    client = IsolatedDreamClient(tmp_path, command=[sys.executable, "-u", "-c", STUB])
    try:
        client.policy({"action_hz": 20})
        assert client.get_models()[0]["servable"]
        client.reset_episode()
        client.set_observation({"video.overhead": "x" * 200000}, {"prompt": "test"}, timestamp=1.0)
        action = client.get_action(commanded={})
        assert len(action["q_l_chunk"]) == 1
        assert client.refill_due(0, 0)
        assert not client.refill_due(0, 1)
        with pytest.raises(RemoteDreamError) as exc:
            client._call("unsupported")
        assert exc.value.retryable
    finally:
        client.close()
    assert client.process.poll() is not None


def test_isolated_reply_timeout_kills_process(tmp_path):
    client = IsolatedDreamClient(
        tmp_path,
        command=[
            sys.executable,
            "-u",
            "-c",
            "import sys,time; sys.stdin.readline(); time.sleep(10)",
        ],
    )
    client.timeout_s = 0.1
    started = time.monotonic()
    try:
        with pytest.raises(SpillError, match="timed out"):
            client.get_models()
        assert time.monotonic() - started < 1
    finally:
        client.close()
