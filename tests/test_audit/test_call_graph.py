# tests/test_audit/test_call_graph.py
from lib.test_audit.call_graph import build_call_graph


def test_build_call_graph_extracts_functions():
    """Extract all function definitions with their calls."""
    code = '''
def outer():
    inner()
    helper()

def inner():
    pass

def helper():
    utility()

def utility():
    pass
'''
    graph = build_call_graph(code, "module.py")

    assert "outer" in graph
    assert set(graph["outer"].calls) == {"inner", "helper"}
    assert graph["inner"].calls == []
    assert graph["helper"].calls == ["utility"]
