#!/usr/bin/env python3
"""
SessionStart hook - Process historical JSONL files incrementally.

On each session start, processes a batch of unprocessed JSONL files
to extract actual token usage data into the v2 telemetry structure.

Features:
- Processes max 25 files per session start (fast startup)
- Tracks progress to avoid re-processing
- Updates telemetry with actual token data
"""

import json
import sys
from pathlib import Path

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

# Processing limit per session start (balance speed vs progress)
MAX_FILES_PER_SESSION = 25


def main():
    """Process a batch of JSONL files on session start."""
    try:
        # Import extractor (will fail gracefully if module not found)
        from jsonl_extractor import process_batch, load_progress, find_jsonl_files, is_file_processed
        
        # Check how many files need processing
        progress = load_progress()
        all_files = find_jsonl_files()
        unprocessed = [f for f in all_files if not is_file_processed(f, progress)]
        
        if not unprocessed:
            # All files processed, nothing to do
            print(json.dumps({
                "status": "complete",
                "message": f"All {len(all_files)} JSONL files processed"
            }))
            return
        
        # Process a batch quietly
        stats = process_batch(max_files=MAX_FILES_PER_SESSION, verbose=False)
        
        # Output status for hook system
        result = {
            "status": "processed",
            "files_processed": stats["processed_this_batch"],
            "tokens_extracted": stats["tokens_extracted"],
            "remaining": stats["remaining"],
            "total_files": stats["total_files"]
        }
        
        # Add progress message if still processing
        if stats["remaining"] > 0:
            pct = ((stats["total_files"] - stats["remaining"]) / stats["total_files"]) * 100
            result["message"] = f"JSONL processing: {pct:.0f}% complete ({stats['remaining']} files remaining)"
        
        print(json.dumps(result))
        
    except ImportError as e:
        # Module not found - skip gracefully
        print(json.dumps({
            "status": "skipped",
            "reason": f"Module not available: {e}"
        }))
    except Exception as e:
        # Log error but don't fail the session
        print(json.dumps({
            "status": "error",
            "error": str(e)
        }), file=sys.stderr)


if __name__ == "__main__":
    main()
