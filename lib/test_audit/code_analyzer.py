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
    - CLI command handlers (Click decorators)
    - (Future: hooks, MCP tools)

    Args:
        code: Python source code to analyze
        file_path: Path to the file being analyzed (for reporting)

    Returns:
        List of EntryPoint objects describing detected entry points
    """
    tree = ast.parse(code)
    entry_points = []

    for node in ast.walk(tree):
        # Check for if __name__ == "__main__" block
        if isinstance(node, ast.If) and _is_main_check(node):
            for stmt in node.body:
                for call in ast.walk(stmt):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                        entry_points.append(EntryPoint(
                            name=call.func.id,
                            file_path=file_path,
                            line_number=call.lineno,
                            source="main_block"
                        ))

        # Check for decorated functions (Click, etc.)
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if _is_cli_decorator(decorator):
                    entry_points.append(EntryPoint(
                        name=node.name,
                        file_path=file_path,
                        line_number=node.lineno,
                        source="cli_handler"
                    ))
                    break

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


def _is_cli_decorator(decorator: ast.expr) -> bool:
    """Check if decorator marks a CLI entry point."""
    # @click.command() or @click.group()
    if isinstance(decorator, ast.Call):
        func = decorator.func
        if isinstance(func, ast.Attribute):
            if func.attr in ("command", "group"):
                return True
        # @group.command()
        if isinstance(func, ast.Attribute) and func.attr == "command":
            return True
    # @click.command (no parens)
    if isinstance(decorator, ast.Attribute):
        if decorator.attr in ("command", "group"):
            return True
    return False
