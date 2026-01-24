# /home/fearsidhe/.claude/plugins/agent-swarm/tests/test_event_client.py
import sys
sys.path.insert(0, '/home/fearsidhe/.claude/plugins/agent-swarm/lib')
from workflow_client import generate_correlation_id  # noqa: E402

def test_generate_correlation_id_returns_string():
    cid = generate_correlation_id()
    assert isinstance(cid, str)
    assert len(cid) > 8
    assert cid.startswith("evt-")

def test_generate_correlation_id_unique():
    ids = [generate_correlation_id() for _ in range(100)]
    assert len(set(ids)) == 100
