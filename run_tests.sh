#!/bin/bash
cd /home/fearsidhe/.claude/plugins/agent-swarm
python -m pytest tests/test_connection_pool.py -v --tb=short 2>&1 | tee /tmp/test_output.txt
echo "---DONE---"
