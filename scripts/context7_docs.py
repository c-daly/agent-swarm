#!/usr/bin/env python3
"""
Context7 documentation lookup - get docs without web search.

Usage:
    python3 context7_docs.py resolve "react hooks"
    python3 context7_docs.py query "/vercel/next.js" "app router setup"
"""

import sys


def resolve_library(query: str) -> str:
    """Resolve library name to Context7 ID."""
    return f"""Use Context7 tool:
  mcp__context7__resolve-library-id
  libraryName: "{query}"
  query: "your specific question"

Returns: Context7 library ID like "/vercel/next.js"

THEN use query-docs with that ID"""


def query_docs(library_id: str, query: str) -> str:
    """Query documentation for a library."""
    return f"""Use Context7 tool:
  mcp__context7__query-docs
  libraryId: "{library_id}"
  query: "{query}"

Returns: Relevant docs + code examples

DO NOT use WebSearch for library documentation - Context7 has it."""


def main():
    if len(sys.argv) < 3:
        print(
            """Usage: context7_docs.py <command> <args>

Commands:
  resolve "<library name>"           - Get Context7 library ID
  query "<library_id>" "<question>"  - Get docs for specific question

Examples:
  context7_docs.py resolve "next.js app router"
  context7_docs.py query "/vercel/next.js" "how to use server actions"

ALWAYS use Context7 instead of WebSearch for:
- Library documentation
- API references
- Framework guides
- Code examples
"""
        )
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "resolve":
        print(resolve_library(sys.argv[2]))
    elif cmd == "query" and len(sys.argv) >= 4:
        print(query_docs(sys.argv[2], sys.argv[3]))
    else:
        print(f"Unknown command or missing args: {cmd}")


if __name__ == "__main__":
    main()
