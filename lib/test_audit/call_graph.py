# lib/test_audit/call_graph.py
"""Build call graphs from Python code."""
import ast
from dataclasses import dataclass, field
from typing import Dict, List, Set


@dataclass
class FunctionInfo:
    name: str
    file_path: str
    line_number: int
    calls: List[str] = field(default_factory=list)
    is_method: bool = False
    class_name: str = ""


def build_call_graph(code: str, file_path: str) -> Dict[str, FunctionInfo]:
    """Build a call graph from Python source code."""
    tree = ast.parse(code)
    graph: Dict[str, FunctionInfo] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            calls = _extract_calls(node)
            graph[node.name] = FunctionInfo(
                name=node.name,
                file_path=file_path,
                line_number=node.lineno,
                calls=calls
            )

    return graph


def _extract_calls(func_node: ast.FunctionDef) -> List[str]:
    """Extract function calls from a function body."""
    calls = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                # method calls like self.method() - just get the method name
                calls.append(node.func.attr)
    return calls


def find_reachable(graph: Dict[str, FunctionInfo], entry_points: List[str]) -> Set[str]:
    """Find all functions reachable from entry points via BFS."""
    reachable: Set[str] = set()
    queue = list(entry_points)

    while queue:
        func_name = queue.pop(0)
        if func_name in reachable:
            continue
        if func_name not in graph:
            continue

        reachable.add(func_name)
        for called in graph[func_name].calls:
            if called not in reachable:
                queue.append(called)

    return reachable
