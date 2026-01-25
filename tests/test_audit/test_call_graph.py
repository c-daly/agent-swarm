# tests/test_audit/test_call_graph.py
from lib.test_audit.call_graph import build_call_graph, find_reachable


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


def test_find_reachable_from_entry_points():
    """Find all functions reachable from entry points."""
    code = '''
def main():
    process()

def process():
    validate()
    transform()

def validate():
    pass

def transform():
    helper()

def helper():
    pass

def unreachable():
    """This function is never called."""
    pass
'''
    graph = build_call_graph(code, "module.py")
    reachable = find_reachable(graph, entry_points=["main"])

    assert reachable == {"main", "process", "validate", "transform", "helper"}
    assert "unreachable" not in reachable
