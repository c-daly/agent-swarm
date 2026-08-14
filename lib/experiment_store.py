"""Experiment (reader, writer) store — the experiment plugin's instance of the
cross-plugin (reader, writer) contract (2026-05-08 architecture).

experiment exposes an ``experiment_reader`` + ``experiment_writer`` pair. The
storage backend is a configuration choice (local filesystem here; a vault
project subtree lands alongside); a registered memory plugin is used
*additively*, never as a hard dependency.

Tenancy: this writer only ever touches experiment's own subtree. Files are
canonical and inspectable on disk — a fresh store instance reads back exactly
what a prior one wrote.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_RUN_RE = re.compile(r"run-(\d+)$")
_FRONT_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
_OBS_FIELDS = ("title", "hypothesis", "changes", "result", "diagnosis", "next_direction")

_OBS_BODY = """# {title}

**Attempt:** {number}
**Hypothesis:** {hypothesis}

## Changes
{changes}

## Result
{result}

## Diagnosis
{diagnosis}

## Next Direction
{next_direction}
"""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def validate_experiment_name(name: str) -> str:
    """Reject names that would escape the experiment's own subtree."""
    if not name or not name.strip():
        raise ValueError("experiment name is required")
    if "/" in name or "\\" in name or name in (".", "..") or name.startswith("."):
        raise ValueError(f"invalid experiment name: {name!r}")
    return name


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return (s or "observation")[:40]


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

@dataclass
class Observation:
    """A single experiment observation (one journal attempt)."""
    title: str
    hypothesis: str = ""
    changes: str = ""
    result: str = ""
    diagnosis: str = ""
    next_direction: str = ""
    run_id: Optional[str] = None   # assigned by the writer
    number: Optional[int] = None   # assigned by the writer


@dataclass
class Run:
    """An experiment run: a bounded attempt sequence with an outcome."""
    run_id: str
    experiment: str
    goal: str = ""
    started_at: str = ""
    ended_at: Optional[str] = None
    outcome: Optional[str] = None
    metrics: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------

class ExperimentWriter(ABC):
    """Write surface. Producers (workflow, hooks, other plugins) call these."""

    @abstractmethod
    def start_run(self, experiment: str, goal: str) -> str:
        """Begin a run; return its run_id."""

    @abstractmethod
    def record_observation(self, run_id: str, observation: Observation) -> str:
        """Append an observation to a run; return its observation id."""

    @abstractmethod
    def end_run(self, run_id: str, outcome: str, metrics: dict) -> None:
        """Finalize a run with an outcome and metrics."""


class ExperimentReader(ABC):
    """Read surface. Consumed by the workflow and sibling plugins."""

    @abstractmethod
    def list_runs(self, experiment: str) -> list[Run]:
        """All runs for an experiment, oldest first."""

    @abstractmethod
    def get_run(self, run_id: str) -> Run:
        """One run by id. Raises KeyError if absent."""

    @abstractmethod
    def observations(self, run_id: str) -> list[Observation]:
        """A run's observations, in order."""


# ---------------------------------------------------------------------------
# Observation (de)serialization — frontmatter is canonical, body is human view
# ---------------------------------------------------------------------------

def _render_observation(obs: Observation, number: int, run_id: str) -> str:
    front = {"run_id": run_id, "number": number, "created_at": _now_iso()}
    for f in _OBS_FIELDS:
        front[f] = getattr(obs, f)
    body = _OBS_BODY.format(number=number, **{k: getattr(obs, k) for k in _OBS_FIELDS})
    dumped = yaml.safe_dump(front, sort_keys=False, allow_unicode=True)
    return f"---\n{dumped}---\n\n{body}"


def _parse_observation(text: str) -> Observation:
    m = _FRONT_RE.match(text)
    if not m:
        raise ValueError("observation file missing frontmatter")
    front = yaml.safe_load(m.group(1)) or {}
    return Observation(
        title=front.get("title", ""),
        hypothesis=front.get("hypothesis", ""),
        changes=front.get("changes", ""),
        result=front.get("result", ""),
        diagnosis=front.get("diagnosis", ""),
        next_direction=front.get("next_direction", ""),
        run_id=front.get("run_id"),
        number=front.get("number"),
    )


# ---------------------------------------------------------------------------
# Local filesystem backend
# ---------------------------------------------------------------------------

class LocalFsExperimentStore(ExperimentWriter, ExperimentReader):
    """Filesystem-backed store rooted at an experiments parent directory.

    Layout::

        <root>/<experiment>/runs/run-<NNN>/run.json
        <root>/<experiment>/runs/run-<NNN>/journal/<NNN>_<slug>.md

    run_id is ``"<experiment>/run-<NNN>"`` so a run is self-locating from its id.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)

    # -- writer --------------------------------------------------------------

    def start_run(self, experiment: str, goal: str) -> str:
        runs_dir = self._runs_dir(experiment)
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_name = f"run-{self._next_run_number(runs_dir):03d}"
        run_id = f"{experiment}/{run_name}"
        run_dir = runs_dir / run_name
        (run_dir / "journal").mkdir(parents=True, exist_ok=True)
        self._write_run(run_dir, Run(run_id=run_id, experiment=experiment,
                                     goal=goal, started_at=_now_iso()))
        return run_id

    def record_observation(self, run_id: str, observation: Observation) -> str:
        run_dir = self._run_dir(run_id)
        if not (run_dir / "run.json").exists():
            raise KeyError(f"no such run: {run_id!r}")
        journal = run_dir / "journal"
        journal.mkdir(parents=True, exist_ok=True)
        number = self._next_obs_number(journal)
        path = journal / f"{number:03d}_{_slug(observation.title)}.md"
        path.write_text(_render_observation(observation, number, run_id))
        return f"{run_id}#{number:03d}"

    def end_run(self, run_id: str, outcome: str, metrics: dict) -> None:
        run = self.get_run(run_id)
        run.outcome = outcome
        run.metrics = dict(metrics or {})
        run.ended_at = _now_iso()
        self._write_run(self._run_dir(run_id), run)

    # -- reader --------------------------------------------------------------

    def list_runs(self, experiment: str) -> list[Run]:
        runs_dir = self._runs_dir(experiment)
        if not runs_dir.exists():
            return []
        return [self._read_run(d) for d in sorted(runs_dir.iterdir())
                if d.is_dir() and _RUN_RE.match(d.name) and (d / "run.json").exists()]

    def get_run(self, run_id: str) -> Run:
        run_dir = self._run_dir(run_id)
        if not (run_dir / "run.json").exists():
            raise KeyError(f"no such run: {run_id!r}")
        return self._read_run(run_dir)

    def observations(self, run_id: str) -> list[Observation]:
        journal = self._run_dir(run_id) / "journal"
        if not journal.exists():
            return []
        return [_parse_observation(p.read_text()) for p in sorted(journal.glob("*.md"))]

    # -- paths / helpers -----------------------------------------------------

    def _runs_dir(self, experiment: str) -> Path:
        validate_experiment_name(experiment)
        return self.root / experiment / "runs"

    def _run_dir(self, run_id: str) -> Path:
        experiment, run_name = self._split_run_id(run_id)
        return self.root / experiment / "runs" / run_name

    @staticmethod
    def _split_run_id(run_id: str) -> tuple[str, str]:
        experiment, _, run_name = run_id.rpartition("/")
        if not experiment or not _RUN_RE.match(run_name):
            raise KeyError(f"malformed run_id: {run_id!r}")
        validate_experiment_name(experiment)
        return experiment, run_name

    @staticmethod
    def _next_run_number(runs_dir: Path) -> int:
        nums = [int(m.group(1)) for d in runs_dir.iterdir()
                if d.is_dir() and (m := _RUN_RE.match(d.name))]
        return max(nums, default=0) + 1

    @staticmethod
    def _next_obs_number(journal: Path) -> int:
        nums = [int(p.name.split("_", 1)[0]) for p in journal.glob("*.md")
                if p.name.split("_", 1)[0].isdigit()]
        return max(nums, default=0) + 1

    @staticmethod
    def _write_run(run_dir: Path, run: Run) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run.json").write_text(json.dumps({
            "run_id": run.run_id,
            "experiment": run.experiment,
            "goal": run.goal,
            "started_at": run.started_at,
            "ended_at": run.ended_at,
            "outcome": run.outcome,
            "metrics": run.metrics,
        }, indent=2))

    @staticmethod
    def _read_run(run_dir: Path) -> Run:
        data = json.loads((run_dir / "run.json").read_text())
        return Run(
            run_id=data["run_id"],
            experiment=data["experiment"],
            goal=data.get("goal", ""),
            started_at=data.get("started_at", ""),
            ended_at=data.get("ended_at"),
            outcome=data.get("outcome"),
            metrics=data.get("metrics", {}),
        )


# ---------------------------------------------------------------------------
# Presence-gated memory mirroring (the "use memory if registered" coupling)
# ---------------------------------------------------------------------------

def _mirror_identity(observation: Observation, run_id: str, obs_id: str) -> Observation:
    """Return a copy of ``observation`` carrying the identity the base writer
    assigned: the run_id, and the sequence number parsed from ``obs_id``
    (format ``<run_id>#<NNN>``). Mirror sinks serialize identity off the object,
    so without this the mirrored doc records run_id='' and number 0 instead of
    the authoritative values. A copy (not in-place) keeps the caller's object
    untouched.
    """
    trailing = obs_id.rpartition("#")[2]
    number = int(trailing) if trailing.isdigit() else observation.number
    return replace(observation, run_id=run_id, number=number)


class MemoryMirrorWriter(ExperimentWriter):
    """Wrap a base writer and, when a memory sink is present and available,
    additively mirror each recorded observation into memory's own store.

    The base write is authoritative; memory mirroring is best-effort — a sink
    that is unavailable or errors never breaks the experiment's own record.
    This is the whole "use memory iff a memory plugin is registered" coupling:
    pass ``sink=None`` (or an unavailable sink) and this is a pure pass-through,
    so experiment lives without memory.
    """

    def __init__(self, base: ExperimentWriter, sink=None):
        self.base = base
        self.sink = sink

    def start_run(self, experiment: str, goal: str) -> str:
        return self.base.start_run(experiment, goal)

    def record_observation(self, run_id: str, observation: Observation) -> str:
        obs_id = self.base.record_observation(run_id, observation)
        if self.sink is not None:
            try:
                if self.sink.available():
                    experiment = run_id.rpartition("/")[0]
                    self.sink.record(experiment, obs_id,
                                     _mirror_identity(observation, run_id, obs_id))
            except Exception:  # best-effort: never break the authoritative write
                logger.warning("experiment: memory mirror failed for %s", obs_id,
                               exc_info=True)
        return obs_id

    def end_run(self, run_id: str, outcome: str, metrics: dict) -> None:
        self.base.end_run(run_id, outcome, metrics)


class MemoryPluginSink:
    """Records experiment observations into the memory plugin's store via its
    ``bin/memory write`` CLI — the same bridge continuity uses.

    Presence-gated: ``available()`` is False when the memory CLI is not
    installed, so callers treat memory as optional.
    """

    _DEFAULT_BIN = Path.home() / ".claude" / "plugins" / "memory" / "bin" / "memory"

    def __init__(self, memory_bin=None, env=None, timeout_seconds: float = 10.0):
        if memory_bin is None:
            env_bin = os.environ.get("MEMORY_BIN")
            memory_bin = Path(env_bin) if env_bin else self._DEFAULT_BIN
        self.memory_bin = Path(memory_bin)
        self.env = env
        self.timeout_seconds = timeout_seconds

    def available(self) -> bool:
        return self.memory_bin.exists()

    def record(self, experiment: str, obs_id: str, observation: Observation) -> None:
        args = self._write_args(experiment, obs_id, observation)
        body = self._render_body(obs_id, observation)
        result = subprocess.run(
            args, input=body, capture_output=True, text=True,
            env=self._subprocess_env(), timeout=self.timeout_seconds,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"memory write failed ({result.returncode}): {detail}")

    def _write_args(self, experiment: str, obs_id: str, observation: Observation) -> list[str]:
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", obs_id).strip("-")
        return [
            str(self.memory_bin), "write",
            "--type", "project",
            "--name", name,
            "--subject", experiment,
            "--description", observation.title or obs_id,
        ]

    def _render_body(self, obs_id: str, observation: Observation) -> str:
        return (
            f"Source: experiment\nObservation: {obs_id}\n\n"
            + _render_observation(observation, observation.number or 0,
                                  observation.run_id or "")
        )

    def _subprocess_env(self) -> dict:
        env = dict(os.environ if self.env is None else self.env)
        if "MEMORY_VAULT_DIR" not in env:
            vault = env.get("VAULT_DIR") or env.get("CONTINUITY_VAULT_DIR")
            if vault:
                env["MEMORY_VAULT_DIR"] = vault
        return env


# ---------------------------------------------------------------------------
# Vault backend + selection
# ---------------------------------------------------------------------------

class VaultExperimentStore(LocalFsExperimentStore):
    """Experiment store rooted at a vault project's experiments subtree:
    ``<vault>/10-projects/<project>/experiments/``. The canonical default.
    """

    def __init__(self, vault_dir, project: str):
        validate_experiment_name(project)
        self.vault_dir = Path(vault_dir)
        self.project = project
        super().__init__(self.vault_dir / "10-projects" / project / "experiments")


def make_experiment_backend(backend: str = "vault", *, root=None,
                            vault_dir=None, project=None) -> LocalFsExperimentStore:
    """Construct the base store (reader+writer) for the chosen backend.

    Backend choice is configuration, not API — ``vault`` (canonical default)
    or ``local``. Plurality lives here, at the implementation level.
    """
    if backend == "local":
        if root is None:
            raise ValueError("local backend requires root=")
        return LocalFsExperimentStore(root)
    if backend == "vault":
        vault_dir = (vault_dir or os.environ.get("EXPERIMENT_VAULT_DIR")
                     or os.environ.get("VAULT_DIR") or os.environ.get("MEMORY_VAULT_DIR"))
        if not vault_dir:
            raise ValueError(
                "vault backend requires vault_dir (or EXPERIMENT_VAULT_DIR/VAULT_DIR)")
        if not project:
            raise ValueError("vault backend requires project=")
        return VaultExperimentStore(vault_dir, project)
    raise ValueError(f"unknown experiment backend: {backend!r}")


def open_experiment_writer(store, *, memory: bool = True) -> ExperimentWriter:
    """Wrap a base store's write surface with presence-gated memory mirroring.

    memory=True attaches a MemoryPluginSink; if no memory plugin is installed
    the sink reports unavailable and writes stay local — memory is optional.
    """
    return MemoryMirrorWriter(store, MemoryPluginSink() if memory else None)
