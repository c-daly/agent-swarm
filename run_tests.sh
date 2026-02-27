#!/bin/bash
cd "${AGENT_SWARM_ROOT:-$(dirname "$0")}"
python -m pytest tests/test_connection_pool.py -v --tb=short 2>&1 | tee /tmp/test_output.txt
echo "---DONE---"
