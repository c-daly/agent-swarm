#!/bin/bash
# View hook activity log
# Usage: ./hook-status.sh [tail|clear|last N]

LOG_FILE="$HOME/.claude/plugins/agent-swarm/.state/hooks.log"

case "$1" in
    tail)
        echo "Tailing hook log... (Ctrl+C to stop)"
        tail -f "$LOG_FILE"
        ;;
    clear)
        rm -f "$LOG_FILE"
        echo "Hook log cleared"
        ;;
    last)
        N="${2:-20}"
        echo "Last $N hook events:"
        echo "─────────────────────────────────────────────────────────────────"
        tail -n "$N" "$LOG_FILE" 2>/dev/null || echo "(no log yet)"
        ;;
    *)
        echo "Hook Activity Log"
        echo "═════════════════════════════════════════════════════════════════"
        if [ -f "$LOG_FILE" ]; then
            echo "Log file: $LOG_FILE"
            echo "Size: $(wc -l < "$LOG_FILE") lines"
            echo ""
            echo "Recent activity (last 15):"
            echo "─────────────────────────────────────────────────────────────────"
            tail -n 15 "$LOG_FILE"
        else
            echo "No hook log yet. Hooks haven't fired."
        fi
        echo ""
        echo "Commands:"
        echo "  ./hook-status.sh tail    - Follow log in real-time"
        echo "  ./hook-status.sh last 50 - Show last 50 entries"
        echo "  ./hook-status.sh clear   - Clear log"
        ;;
esac
