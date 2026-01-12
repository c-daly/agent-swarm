"""Classification validator to prevent agents gaming complexity levels."""

ARCHITECTURAL_KEYWORDS = {
    "refactor", "redesign", "migrate", "rewrite",
    "architecture", "restructure", "overhaul",
}


def validate_classification(claimed: str, task: str, state: dict) -> tuple[bool, str]:
    """Validate classification matches actual complexity.
    
    Args:
        claimed: The claimed classification level (TRIVIAL, SIMPLE, COMPLEX, etc.)
        task: The task description to analyze
        state: Current agent state containing execution metadata
    
    Returns:
        Tuple of (valid, reason) where valid is True if classification is correct,
        and reason is "OK" or an error message explaining the violation.
    """
    # SIMPLE can't have multiple files
    if claimed == "SIMPLE":
        files_edited = len(state.get("files_edited", set()))
        if files_edited > 1:
            return False, f"SIMPLE allows 1 file, edited {files_edited}. Use /iterate or /orchestrate."

    # TRIVIAL/SIMPLE can't have architectural keywords
    if claimed in ("TRIVIAL", "SIMPLE"):
        for keyword in ARCHITECTURAL_KEYWORDS:
            if keyword in task.lower():
                return False, f"'{keyword}' requires COMPLEX classification."

    return True, "OK"
