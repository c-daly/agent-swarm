#!/usr/bin/env python3
"""
Phase Executor - State Machine for Workflow Phases

Each phase is a SCRIPT, not a suggestion. The orchestrator executes the script,
it doesn't decide what to do. This ensures predictable, repeatable behavior.

Phase Structure:
- entry_actions: List of actions to execute when entering phase
- wait_for: What must complete before proceeding
- exit_to: Next phase(s) based on conditions
- max_iterations: Limit for loops (e.g., debug -> implement -> review cycles)

Actions can be:
- spawn_agent(type, prompt_template) - spawn a subagent
- spawn_parallel([agents]) - spawn multiple agents in parallel
- wait_all() - wait for all spawned agents to complete
- checkpoint(message) - pause for user confirmation
- transition(phase) - move to next phase
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

STATE_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/session.json"
WORKFLOW_FILE = Path.home() / ".claude/plugins/agent-swarm/config/workflow.json"


class ActionType(Enum):
    SPAWN_AGENT = "spawn_agent"
    SPAWN_PARALLEL = "spawn_parallel"
    WAIT_ALL = "wait_all"
    CHECKPOINT = "checkpoint"
    TRANSITION = "transition"
    COLLECT_RESULTS = "collect_results"


@dataclass
class PhaseAction:
    """A single action in a phase script."""
    action_type: ActionType
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PhaseDefinition:
    """Definition of a workflow phase as a script."""
    name: str
    description: str
    entry_actions: List[PhaseAction]
    exit_conditions: Dict[str, str]  # condition -> next_phase
    max_iterations: int = 1
    checkpoint_before_exit: bool = False


# Phase definitions as executable scripts
PHASE_SCRIPTS: Dict[str, PhaseDefinition] = {
    "intake": PhaseDefinition(
        name="intake",
        description="Classify request and determine path",
        entry_actions=[
            PhaseAction(ActionType.SPAWN_AGENT, {
                "type": "classifier",
                "prompt": "Classify this request: {user_request}\n\nDetermine:\n1. Complexity: trivial | normal | complex\n2. Type: bug_fix | feature | refactor | question | research\n3. Scope: single_file | multi_file | system_wide\n\nOutput JSON: {complexity, type, scope, reasoning}"
            }),
            PhaseAction(ActionType.WAIT_ALL, {}),
            PhaseAction(ActionType.COLLECT_RESULTS, {"store_as": "classification"}),
        ],
        exit_conditions={
            "classification.complexity == 'trivial'": "implement",
            "classification.type == 'question'": "research",
            "classification.type == 'research'": "research",
            "default": "explore"
        },
        checkpoint_before_exit=True
    ),

    "research": PhaseDefinition(
        name="research",
        description="Deep research for complex/unfamiliar domains",
        entry_actions=[
            PhaseAction(ActionType.SPAWN_PARALLEL, {
                "agents": [
                    {"type": "researcher", "prompt": "Research: {topic}\n\nFind:\n1. Best practices\n2. Common patterns\n3. Pitfalls to avoid\n\nOutput: concise summary with actionable guidance"},
                    {"type": "explorer", "prompt": "Find relevant code in this codebase for: {topic}\n\nOutput: list of relevant files with brief descriptions"}
                ]
            }),
            PhaseAction(ActionType.WAIT_ALL, {}),
            PhaseAction(ActionType.COLLECT_RESULTS, {"store_as": "research_results"}),
        ],
        exit_conditions={
            "default": "design"
        }
    ),

    "explore": PhaseDefinition(
        name="explore",
        description="Understand codebase structure for the task",
        entry_actions=[
            PhaseAction(ActionType.SPAWN_AGENT, {
                "type": "explorer",
                "prompt": "Explore codebase for: {user_request}\n\nFind:\n1. Relevant files and functions\n2. Dependencies and relationships\n3. Patterns already used\n\nOutput: structured summary for implementation planning"
            }),
            PhaseAction(ActionType.WAIT_ALL, {}),
            PhaseAction(ActionType.COLLECT_RESULTS, {"store_as": "exploration_results"}),
        ],
        exit_conditions={
            "default": "design"
        }
    ),

    "design": PhaseDefinition(
        name="design",
        description="Create implementation plan",
        entry_actions=[
            PhaseAction(ActionType.SPAWN_AGENT, {
                "type": "architect",
                "prompt": "Design implementation for: {user_request}\n\nContext:\n{exploration_results}\n{research_results}\n\nCreate:\n1. Step-by-step implementation plan\n2. Files to create/modify\n3. Test strategy\n\nOutput: actionable implementation spec"
            }),
            PhaseAction(ActionType.WAIT_ALL, {}),
            PhaseAction(ActionType.COLLECT_RESULTS, {"store_as": "design_spec"}),
        ],
        exit_conditions={
            "default": "implement"
        },
        checkpoint_before_exit=True
    ),

    "implement": PhaseDefinition(
        name="implement",
        description="Execute implementation plan",
        entry_actions=[
            # Implementation might spawn multiple agents for different files
            PhaseAction(ActionType.SPAWN_AGENT, {
                "type": "implementer",
                "prompt": "Implement according to this spec:\n\n{design_spec}\n\nRules:\n- Make minimal, focused changes\n- Follow existing patterns\n- No over-engineering\n\nExecute the plan step by step."
            }),
            PhaseAction(ActionType.WAIT_ALL, {}),
            PhaseAction(ActionType.COLLECT_RESULTS, {"store_as": "implementation_results"}),
        ],
        exit_conditions={
            "default": "review"
        }
    ),

    "review": PhaseDefinition(
        name="review",
        description="Verify implementation quality",
        entry_actions=[
            PhaseAction(ActionType.SPAWN_PARALLEL, {
                "agents": [
                    {"type": "reviewer", "prompt": "Review changes:\n\n{implementation_results}\n\nCheck:\n1. Correctness\n2. Style consistency\n3. Edge cases\n4. Security issues\n\nOutput: issues list or APPROVED"},
                    {"type": "tester", "prompt": "Run tests for:\n\n{implementation_results}\n\nExecute relevant test suite and report results."}
                ]
            }),
            PhaseAction(ActionType.WAIT_ALL, {}),
            PhaseAction(ActionType.COLLECT_RESULTS, {"store_as": "review_results"}),
        ],
        exit_conditions={
            "review_results.has_issues": "debug",
            "review_results.tests_failed": "debug",
            "default": "git"
        },
        max_iterations=3,
        checkpoint_before_exit=True
    ),

    "debug": PhaseDefinition(
        name="debug",
        description="Fix issues found in review",
        entry_actions=[
            PhaseAction(ActionType.SPAWN_AGENT, {
                "type": "debugger",
                "prompt": "Fix these issues:\n\n{review_results}\n\nApply minimal fixes to resolve each issue."
            }),
            PhaseAction(ActionType.WAIT_ALL, {}),
            PhaseAction(ActionType.COLLECT_RESULTS, {"store_as": "debug_results"}),
        ],
        exit_conditions={
            "default": "review"  # Back to review for verification
        },
        max_iterations=3
    ),

    "git": PhaseDefinition(
        name="git",
        description="Commit and optionally push changes",
        entry_actions=[
            PhaseAction(ActionType.CHECKPOINT, {
                "message": "Ready to commit. Review changes and approve."
            }),
            PhaseAction(ActionType.SPAWN_AGENT, {
                "type": "git-agent",
                "prompt": "Commit changes:\n\nSummary: {user_request}\nChanges: {implementation_results}\n\nCreate descriptive commit message and commit."
            }),
            PhaseAction(ActionType.WAIT_ALL, {}),
        ],
        exit_conditions={
            "default": "complete"
        },
        checkpoint_before_exit=True
    ),
}


class PhaseExecutor:
    """
    Executes phase scripts in a deterministic manner.

    The orchestrator doesn't decide what to do - it follows the script.
    This ensures every task follows the same pattern, just with different inputs.
    """

    def __init__(self):
        self.state = self._load_state()
        self.current_phase = self.state.get("phase", "intake")
        self.context = self.state.get("phase_context", {})
        self.iteration_counts = self.state.get("iteration_counts", {})
        self.pending_agents = self.state.get("pending_agents", [])
        self.completed_agents = self.state.get("completed_agents", [])

    def _load_state(self) -> dict:
        """Load session state."""
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text())
            except:
                pass
        return {}

    def _save_state(self):
        """Save session state."""
        self.state["phase"] = self.current_phase
        self.state["phase_context"] = self.context
        self.state["iteration_counts"] = self.iteration_counts
        self.state["pending_agents"] = self.pending_agents
        self.state["completed_agents"] = self.completed_agents
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(self.state, indent=2))

    def get_next_action(self) -> Optional[Dict[str, Any]]:
        """
        Get the next action the orchestrator MUST take.

        Returns an action dict that the orchestrator must execute,
        or None if waiting for agents to complete.
        """
        phase = PHASE_SCRIPTS.get(self.current_phase)
        if not phase:
            return {"action": "error", "message": f"Unknown phase: {self.current_phase}"}

        # Check iteration limit
        count = self.iteration_counts.get(self.current_phase, 0)
        if count >= phase.max_iterations:
            return {
                "action": "error",
                "message": f"Phase {self.current_phase} exceeded max iterations ({phase.max_iterations})"
            }

        # Get current action index
        action_index = self.state.get("action_index", 0)

        if action_index >= len(phase.entry_actions):
            # All actions complete - evaluate exit condition
            return self._evaluate_exit_conditions(phase)

        action = phase.entry_actions[action_index]
        return self._format_action(action, action_index)

    def _format_action(self, action: PhaseAction, index: int) -> Dict[str, Any]:
        """Format an action for the orchestrator to execute."""

        if action.action_type == ActionType.SPAWN_AGENT:
            prompt = self._expand_template(action.params.get("prompt", ""))
            return {
                "action": "spawn_agent",
                "type": action.params.get("type", "general-purpose"),
                "prompt": prompt,
                "action_index": index
            }

        elif action.action_type == ActionType.SPAWN_PARALLEL:
            agents = []
            for agent_def in action.params.get("agents", []):
                prompt = self._expand_template(agent_def.get("prompt", ""))
                agents.append({
                    "type": agent_def.get("type", "general-purpose"),
                    "prompt": prompt
                })
            return {
                "action": "spawn_parallel",
                "agents": agents,
                "action_index": index
            }

        elif action.action_type == ActionType.WAIT_ALL:
            if self.pending_agents:
                return {
                    "action": "waiting",
                    "message": f"Waiting for {len(self.pending_agents)} agent(s) to complete",
                    "pending": self.pending_agents
                }
            else:
                # No pending agents, advance to next action
                self.state["action_index"] = index + 1
                self._save_state()
                return self.get_next_action()

        elif action.action_type == ActionType.COLLECT_RESULTS:
            store_as = action.params.get("store_as", "results")
            self.context[store_as] = self._collect_agent_results()
            self.state["action_index"] = index + 1
            self._save_state()
            return self.get_next_action()

        elif action.action_type == ActionType.CHECKPOINT:
            return {
                "action": "checkpoint",
                "message": action.params.get("message", "Checkpoint - awaiting user approval"),
                "action_index": index
            }

        elif action.action_type == ActionType.TRANSITION:
            next_phase = action.params.get("phase", "complete")
            return self._transition_to(next_phase)

        return {"action": "unknown", "type": str(action.action_type)}

    def _expand_template(self, template: str) -> str:
        """Expand template variables with context values."""
        result = template
        for key, value in self.context.items():
            if isinstance(value, str):
                result = result.replace(f"{{{key}}}", value)
            elif isinstance(value, dict):
                # For nested access like {classification.complexity}
                for subkey, subval in value.items():
                    result = result.replace(f"{{{key}.{subkey}}}", str(subval))
                # Also provide full JSON for the object
                result = result.replace(f"{{{key}}}", json.dumps(value, indent=2))

        # Also expand from state
        if "user_request" in self.state:
            result = result.replace("{user_request}", self.state["user_request"])
        if "task_summary" in self.state:
            result = result.replace("{task_summary}", self.state["task_summary"])

        return result

    def _collect_agent_results(self) -> Dict[str, Any]:
        """Collect results from completed agents."""
        results = {}
        for agent in self.completed_agents:
            agent_id = agent.get("id", "unknown")
            results[agent_id] = agent.get("result", "")

        # Clear completed agents
        self.completed_agents = []
        return results

    def _evaluate_exit_conditions(self, phase: PhaseDefinition) -> Dict[str, Any]:
        """Evaluate exit conditions and determine next phase."""

        if phase.checkpoint_before_exit:
            # Check if checkpoint was already approved
            if not self.state.get(f"checkpoint_approved_{self.current_phase}"):
                return {
                    "action": "checkpoint",
                    "message": f"Phase {self.current_phase} complete. Review and approve to continue.",
                    "is_exit_checkpoint": True
                }

        # Evaluate conditions in order
        for condition, next_phase in phase.exit_conditions.items():
            if condition == "default":
                continue
            if self._evaluate_condition(condition):
                return self._transition_to(next_phase)

        # Default transition
        default_phase = phase.exit_conditions.get("default", "complete")
        return self._transition_to(default_phase)

    def _evaluate_condition(self, condition: str) -> bool:
        """Evaluate an exit condition against current context."""
        # Simple evaluation - in production this would be more robust
        try:
            # Handle dot notation like "classification.complexity == 'trivial'"
            parts = condition.split()
            if len(parts) == 3:
                left, op, right = parts

                # Get left value from context
                left_parts = left.split(".")
                value = self.context
                for part in left_parts:
                    if isinstance(value, dict):
                        value = value.get(part, None)
                    else:
                        value = None
                        break

                # Clean up right value
                right = right.strip("'\"")

                # Compare
                if op == "==":
                    return str(value) == right
                elif op == "!=":
                    return str(value) != right

            return False
        except:
            return False

    def _transition_to(self, next_phase: str) -> Dict[str, Any]:
        """Transition to the next phase."""
        old_phase = self.current_phase

        # Update iteration count for old phase
        self.iteration_counts[old_phase] = self.iteration_counts.get(old_phase, 0) + 1

        # Reset action index for new phase
        self.state["action_index"] = 0
        self.current_phase = next_phase

        self._save_state()

        return {
            "action": "transition",
            "from_phase": old_phase,
            "to_phase": next_phase,
            "message": f"Transitioning from {old_phase} to {next_phase}"
        }

    def agent_spawned(self, agent_id: str, agent_type: str):
        """Record that an agent was spawned."""
        self.pending_agents.append({
            "id": agent_id,
            "type": agent_type,
            "spawned_at": self.current_phase
        })
        self._save_state()

    def agent_completed(self, agent_id: str, result: str):
        """Record that an agent completed."""
        # Move from pending to completed
        for i, agent in enumerate(self.pending_agents):
            if agent.get("id") == agent_id:
                agent["result"] = result
                self.completed_agents.append(agent)
                self.pending_agents.pop(i)
                break
        self._save_state()

    def checkpoint_approved(self):
        """Record that a checkpoint was approved."""
        self.state[f"checkpoint_approved_{self.current_phase}"] = True
        self.state["action_index"] = self.state.get("action_index", 0) + 1
        self._save_state()

    def get_status(self) -> Dict[str, Any]:
        """Get current execution status."""
        phase = PHASE_SCRIPTS.get(self.current_phase)
        return {
            "phase": self.current_phase,
            "phase_description": phase.description if phase else "Unknown",
            "action_index": self.state.get("action_index", 0),
            "total_actions": len(phase.entry_actions) if phase else 0,
            "pending_agents": len(self.pending_agents),
            "completed_agents": len(self.completed_agents),
            "iteration_counts": self.iteration_counts,
            "context_keys": list(self.context.keys())
        }


def get_orchestrator_instruction(executor: PhaseExecutor) -> str:
    """
    Generate instruction text for the orchestrator.

    This tells the orchestrator exactly what to do next,
    not what options it has.
    """
    action = executor.get_next_action()

    if action["action"] == "spawn_agent":
        return f"""[PHASE: {executor.current_phase.upper()}]

YOUR NEXT ACTION (MANDATORY):

Spawn a {action['type']} subagent with this prompt:

---
{action['prompt']}
---

Use: Task(subagent_type="{action['type']}", prompt="<the prompt above>")

Do not skip this step. Do not modify the prompt significantly.
Execute this action now."""

    elif action["action"] == "spawn_parallel":
        agents_text = "\n\n".join([
            f"Agent {i+1} ({a['type']}):\n{a['prompt']}"
            for i, a in enumerate(action["agents"])
        ])
        return f"""[PHASE: {executor.current_phase.upper()}]

YOUR NEXT ACTION (MANDATORY):

Spawn these {len(action['agents'])} subagents IN PARALLEL:

---
{agents_text}
---

Use multiple Task() calls in a single response to run them in parallel.
Do not skip any agent. Execute all of them now."""

    elif action["action"] == "waiting":
        return f"""[PHASE: {executor.current_phase.upper()}]

WAITING FOR AGENTS:

{action['message']}

Pending: {action['pending']}

Do not proceed until all agents complete and report results."""

    elif action["action"] == "checkpoint":
        return f"""[PHASE: {executor.current_phase.upper()}]

CHECKPOINT - AWAITING APPROVAL:

{action['message']}

Wait for user confirmation before proceeding."""

    elif action["action"] == "transition":
        return f"""[PHASE TRANSITION]

{action['message']}

Automatically proceeding to {action['to_phase']} phase.
Get next action for the new phase."""

    elif action["action"] == "error":
        return f"""[ERROR]

{action['message']}

Cannot proceed. User intervention required."""

    else:
        return f"Unknown action: {action}"


# Module-level instance for hook integration
_executor: Optional[PhaseExecutor] = None

def get_executor() -> PhaseExecutor:
    """Get or create the phase executor instance."""
    global _executor
    if _executor is None:
        _executor = PhaseExecutor()
    return _executor


if __name__ == "__main__":
    # Self-test
    print("Phase Executor Self-Test")
    print("=" * 50)

    executor = PhaseExecutor()
    status = executor.get_status()

    print(f"\nCurrent Status:")
    print(f"  Phase: {status['phase']}")
    print(f"  Action: {status['action_index']}/{status['total_actions']}")
    print(f"  Pending agents: {status['pending_agents']}")

    print(f"\nNext Action:")
    action = executor.get_next_action()
    print(f"  Type: {action.get('action')}")

    print(f"\nOrchestrator Instruction:")
    instruction = get_orchestrator_instruction(executor)
    print(instruction[:500] + "..." if len(instruction) > 500 else instruction)
