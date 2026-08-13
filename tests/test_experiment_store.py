"""Tests for the experiment (reader, writer) store.

Slice 1: the local-filesystem backend implementing the experiment_reader /
experiment_writer contract (start_run / record_observation / end_run;
list_runs / get_run / observations). Storage is canonical + inspectable on
disk; a fresh store instance reads back what a prior one wrote.
"""

import pytest

from experiment_store import (
    Observation,
    Run,
    ExperimentReader,
    ExperimentWriter,
    LocalFsExperimentStore,
)


@pytest.fixture
def store(tmp_path):
    return LocalFsExperimentStore(tmp_path / "experiments")


def test_backend_implements_both_reader_and_writer(store):
    assert isinstance(store, ExperimentReader)
    assert isinstance(store, ExperimentWriter)


def test_start_run_returns_locatable_run(store):
    run_id = store.start_run("exp-a", "objective X")
    run = store.get_run(run_id)
    assert isinstance(run, Run)
    assert run.experiment == "exp-a"
    assert run.goal == "objective X"
    assert run.started_at
    assert run.ended_at is None


def test_record_observation_numbers_sequentially(store):
    run_id = store.start_run("exp-a", "g")
    store.record_observation(run_id, Observation(title="first", hypothesis="h1"))
    store.record_observation(run_id, Observation(title="second", changes="c2"))
    obs = store.observations(run_id)
    assert [o.number for o in obs] == [1, 2]
    assert obs[0].title == "first"
    assert obs[0].hypothesis == "h1"
    assert obs[0].run_id == run_id
    assert obs[1].changes == "c2"


def test_observations_empty_for_new_run(store):
    run_id = store.start_run("exp-a", "g")
    assert store.observations(run_id) == []


def test_end_run_records_outcome_and_metrics(store):
    run_id = store.start_run("exp-a", "g")
    store.end_run(run_id, outcome="success", metrics={"accuracy": 0.95})
    run = store.get_run(run_id)
    assert run.outcome == "success"
    assert run.metrics["accuracy"] == 0.95
    assert run.ended_at is not None


def test_list_runs_scoped_to_experiment(store):
    r1 = store.start_run("exp-a", "g")
    r2 = store.start_run("exp-a", "g2")
    store.start_run("exp-b", "g3")
    runs = store.list_runs("exp-a")
    assert {r.run_id for r in runs} == {r1, r2}


def test_multiline_observation_prose_round_trips(store):
    run_id = store.start_run("exp-a", "g")
    prose = "line one\nline two\n\nparagraph two"
    store.record_observation(run_id, Observation(title="t", diagnosis=prose))
    (obs,) = store.observations(run_id)
    assert obs.diagnosis == prose


def test_persists_across_instances(tmp_path):
    root = tmp_path / "experiments"
    run_id = LocalFsExperimentStore(root).start_run("exp-a", "g")
    LocalFsExperimentStore(root).record_observation(run_id, Observation(title="t"))
    obs = LocalFsExperimentStore(root).observations(run_id)
    assert len(obs) == 1
    assert obs[0].title == "t"


def test_get_run_missing_raises(store):
    with pytest.raises(KeyError):
        store.get_run("exp-a/run-999")


# ---------------------------------------------------------------------------
# Slice 2: presence-gated memory mirroring
# ---------------------------------------------------------------------------

from experiment_store import MemoryMirrorWriter, MemoryPluginSink  # noqa: E402


class _FakeSink:
    def __init__(self, available=True, fail=False):
        self._available = available
        self._fail = fail
        self.records = []

    def available(self):
        return self._available

    def record(self, experiment, obs_id, observation):
        if self._fail:
            raise RuntimeError("memory down")
        self.records.append((experiment, obs_id, observation))


def test_mirrors_observation_when_sink_available(tmp_path):
    base = LocalFsExperimentStore(tmp_path / "e")
    sink = _FakeSink(available=True)
    w = MemoryMirrorWriter(base, sink)
    rid = w.start_run("exp", "g")
    w.record_observation(rid, Observation(title="t"))
    assert len(sink.records) == 1
    assert sink.records[0][0] == "exp"
    assert len(base.observations(rid)) == 1  # base is authoritative


def test_no_mirror_when_sink_unavailable(tmp_path):
    base = LocalFsExperimentStore(tmp_path / "e")
    sink = _FakeSink(available=False)
    w = MemoryMirrorWriter(base, sink)
    rid = w.start_run("exp", "g")
    w.record_observation(rid, Observation(title="t"))
    assert sink.records == []
    assert len(base.observations(rid)) == 1


def test_sink_failure_does_not_break_base_write(tmp_path):
    base = LocalFsExperimentStore(tmp_path / "e")
    sink = _FakeSink(available=True, fail=True)
    w = MemoryMirrorWriter(base, sink)
    rid = w.start_run("exp", "g")
    w.record_observation(rid, Observation(title="t"))  # must not raise
    assert len(base.observations(rid)) == 1


def test_none_sink_is_pure_passthrough(tmp_path):
    base = LocalFsExperimentStore(tmp_path / "e")
    w = MemoryMirrorWriter(base, None)
    rid = w.start_run("exp", "g")
    w.record_observation(rid, Observation(title="t"))
    assert len(base.observations(rid)) == 1


def test_mirror_writer_delegates_run_lifecycle(tmp_path):
    base = LocalFsExperimentStore(tmp_path / "e")
    w = MemoryMirrorWriter(base, _FakeSink())
    rid = w.start_run("exp", "g")
    w.end_run(rid, "success", {"acc": 1.0})
    assert base.get_run(rid).outcome == "success"


def test_memory_sink_unavailable_when_bin_missing(tmp_path):
    sink = MemoryPluginSink(memory_bin=tmp_path / "nope" / "memory")
    assert sink.available() is False


def test_memory_sink_maps_observation_to_memory_write_args(tmp_path):
    sink = MemoryPluginSink(memory_bin=tmp_path / "memory")
    obs = Observation(title="My Title", run_id="exp-a/run-001", number=2)
    args = sink._write_args("exp-a", "exp-a/run-001#002", obs)
    assert args[:2] == [str(tmp_path / "memory"), "write"]
    assert "--type" in args and "project" in args
    assert "--subject" in args and "exp-a" in args
    # name must be a safe basename (no '/' or '#')
    name = args[args.index("--name") + 1]
    assert "/" not in name and "#" not in name
    assert "--description" in args and "My Title" in args


# ---------------------------------------------------------------------------
# Slice 3/4: vault backend + backend-selection factory
# ---------------------------------------------------------------------------

from experiment_store import (  # noqa: E402
    VaultExperimentStore,
    make_experiment_backend,
    open_experiment_writer,
)


def test_vault_backend_writes_under_project_experiments(tmp_path):
    vault = tmp_path / "vault"
    store = VaultExperimentStore(vault, "agent-swarm")
    rid = store.start_run("exp-a", "g")
    store.record_observation(rid, Observation(title="t"))
    expected = vault / "10-projects" / "agent-swarm" / "experiments" / "exp-a" / "runs"
    assert expected.exists()
    assert len(store.observations(rid)) == 1


def test_make_backend_local(tmp_path):
    assert isinstance(make_experiment_backend("local", root=tmp_path / "e"),
                      LocalFsExperimentStore)


def test_make_backend_vault(tmp_path):
    assert isinstance(make_experiment_backend("vault", vault_dir=tmp_path, project="p"),
                      VaultExperimentStore)


def test_make_backend_local_requires_root():
    with pytest.raises(ValueError):
        make_experiment_backend("local")


def test_make_backend_vault_requires_project(tmp_path):
    with pytest.raises(ValueError):
        make_experiment_backend("vault", vault_dir=tmp_path)


def test_make_backend_unknown():
    with pytest.raises(ValueError):
        make_experiment_backend("nope", root="x")


def test_open_writer_wraps_with_memory_mirror(tmp_path):
    store = make_experiment_backend("local", root=tmp_path / "e")
    w = open_experiment_writer(store)
    assert isinstance(w, MemoryMirrorWriter)
    assert isinstance(w.sink, MemoryPluginSink)


def test_open_writer_without_memory(tmp_path):
    store = make_experiment_backend("local", root=tmp_path / "e")
    assert open_experiment_writer(store, memory=False).sink is None
