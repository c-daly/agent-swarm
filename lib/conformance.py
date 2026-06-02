"""Static workflow-governance conformance checks (Layer 1 of the conformance harness, #104).

Verifies — WITHOUT the daemon — that each workflow's declared governance is actually
*enforceable*: the three config sources have to agree.

  * config/workflows/<wf>.yaml         — declared intent (the phases of the workflow)
  * config/permissions.yaml workflows  — the L1 (workflow/phase) enforcement layer
  * lib/permission_query.py _KNOWN_WORKFLOWS — the recognition gate

Why it matters: PermissionChecker.check resolves a cascade
(superblock -> workflows[wf][phase] -> agents[type] -> roles -> global -> default-deny),
where L1 is `if workflow in wf_config and phase in wf_config[workflow]`. A workflow that
declares phases but is missing from _KNOWN_WORKFLOWS, or has no workflows[<wf>] block in
permissions.yaml, never reaches its L1 layer — the phase restrictions silently fall through
to the agent-type/role/global layers (fail-open). This check flags that statically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parent.parent
_WORKFLOWS_DIR = _REPO / "config" / "workflows"
_PERMISSIONS = _REPO / "config" / "permissions.yaml"
_PERMISSION_QUERY = _REPO / "lib" / "permission_query.py"


@dataclass
class WorkflowConformance:
    """Static governance-enforceability report for one workflow YAML."""
    name: str
    known: bool                                  # listed in _KNOWN_WORKFLOWS
    has_perms_block: bool                        # has a workflows[name] block in permissions.yaml
    yaml_phases: list = field(default_factory=list)
    perms_phases: list = field(default_factory=list)
    missing_phases: list = field(default_factory=list)   # declared in YAML, absent at L1
    extra_phases: list = field(default_factory=list)      # present at L1, not declared in YAML
    fail_open: bool = False                      # declares phases but L1 is unreachable/incomplete
    notes: list = field(default_factory=list)


def _load_known_workflows() -> set:
    m = re.search(r"_KNOWN_WORKFLOWS\s*=\s*\[(.*?)\]", _PERMISSION_QUERY.read_text(), re.S)
    return set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()


def _load_workflow_yamls() -> dict:
    out = {}
    for path in sorted(_WORKFLOWS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict) or "name" not in data:
            continue
        out[data["name"]] = [
            p["name"] for p in data.get("phases", [])
            if isinstance(p, dict) and "name" in p
        ]
    return out


def _load_permissions_workflows() -> dict:
    data = yaml.safe_load(_PERMISSIONS.read_text()) or {}
    wf = data.get("workflows", {}) or {}
    return {name: list(block.keys()) for name, block in wf.items() if isinstance(block, dict)}


def analyze() -> dict:
    """Return {'workflows': [WorkflowConformance...], 'phantom_known': [names...]}.

    phantom_known = entries in _KNOWN_WORKFLOWS that have no workflow YAML.
    """
    known = _load_known_workflows()
    yamls = _load_workflow_yamls()
    perms = _load_permissions_workflows()

    reports = []
    for name, yaml_phases in sorted(yamls.items()):
        is_known = name in known
        perms_phases = perms.get(name)
        has_block = perms_phases is not None
        missing = [ph for ph in yaml_phases if ph not in (perms_phases or [])]
        extra = [ph for ph in (perms_phases or []) if ph not in yaml_phases]
        fail_open = (not is_known) or (not has_block) or bool(missing)
        notes = []
        if not is_known:
            notes.append("absent from _KNOWN_WORKFLOWS -> not recognized at runtime (fail-open)")
        if not has_block:
            notes.append(f"no workflows['{name}'] block in permissions.yaml -> L1 layer skipped (fail-open)")
        if missing:
            notes.append(f"phases declared in YAML but absent at L1: {missing}")
        if extra:
            notes.append(f"phases enforced at L1 but not declared in YAML: {extra}")
        reports.append(WorkflowConformance(
            name=name, known=is_known, has_perms_block=has_block,
            yaml_phases=yaml_phases, perms_phases=perms_phases or [],
            missing_phases=missing, extra_phases=extra,
            fail_open=fail_open, notes=notes,
        ))

    phantom_known = sorted(known - set(yamls))
    return {"workflows": reports, "phantom_known": phantom_known}


def _main() -> None:
    result = analyze()
    print("Workflow governance conformance (static):\n")
    for r in result["workflows"]:
        flag = "FAIL-OPEN" if r.fail_open else "ok"
        print(f"  [{flag:9}] {r.name}")
        print(f"             known={r.known}  perms_block={r.has_perms_block}")
        for note in r.notes:
            print(f"             - {note}")
    if result["phantom_known"]:
        print(f"\n  _KNOWN_WORKFLOWS entries with no workflow YAML: {result['phantom_known']}")


if __name__ == "__main__":
    _main()
