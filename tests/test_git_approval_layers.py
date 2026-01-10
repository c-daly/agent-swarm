#!/usr/bin/env python3
"""Tests for 3-layer git approval system"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))
import sys; sys.path.insert(0, "hooks")
from combined_enforcement import check_git_approval_layers

def test_layer1_no_approval():
    print("\n[TEST] Layer 1: No approval")
    state = {}
    messages = [{"role": "user", "content": "write code"}]
    result = check_git_approval_layers("Bash", {"command": "git commit -m 'test'"}, state, messages)
    assert result is not None, "Should block"
    print("✅ PASS")

def test_all_layers_ok():
    print("\n[TEST] All layers satisfied")
    state = {"user_approved_commit": True, "tests_executed": True, "verify_signal_given": True}
    messages = [{"role": "user", "content": "approved"}]
    result = check_git_approval_layers("Bash", {"command": "git commit -m 'test'"}, state, messages)
    assert result is None, "Should allow"
    print("✅ PASS")

print("="*60)
print("GIT APPROVAL TESTS")
print("="*60)
test_layer1_no_approval()
test_all_layers_ok()
print("\n" + "="*60)
print("ALL TESTS PASSED")
print("="*60)
