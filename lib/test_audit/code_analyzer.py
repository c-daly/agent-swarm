"""Analyze production code to identify critical paths."""
import ast
from dataclasses import dataclass
from typing import List


@dataclass
class EntryPoint:
    name: str
    file_path: str
    line_number: int
    source: str  # "main_block", "cli_handler", "hook", "mcp_tool"


def find_entry_points(code: str, file_path: str) -> List[EntryPoint]:
    """Find entry points in Python code.

    Entry points are functions that serve as starting points for execution:
    - Functions called in if __name__ == "__main__" blocks
    - (Future: CLI handlers, hooks, MCP tools)

    Args:
        code: Python source code to analyze
        file_path: Path to the file being analyzed (for reporting)

    Returns:
        List of EntryPoint objects describing detected entry points
    """
    tree = ast.parse(code)
    entry_points = []

    # Find functions called in if __name__ == "__main__" block
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            # Check for if __name__ == "__main__"
            if _is_main_check(node):
                # Find function calls in the block
                for stmt in node.body:
                    for call in ast.walk(stmt):
                        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                            entry_points.append(EntryPoint(
                                name=call.func.id,
                                file_path=file_path,
                                line_number=call.lineno,
                                source="main_block"
                            ))
    return entry_points


def _is_main_check(node: ast.If) -> bool:
    """Check if this is an 'if __name__ == "__main__"' block."""
    test = node.test
    if isinstance(test, ast.Compare):
        if isinstance(test.left, ast.Name) and test.left.id == "__name__":
            if test.ops and isinstance(test.ops[0], ast.Eq):
                if test.comparators and isinstance(test.comparators[0], ast.Constant):
                    return test.comparators[0].value == "__main__"
    return False
