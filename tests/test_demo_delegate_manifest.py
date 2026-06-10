"""The demo delegate manifest parses and carries tier fields end-to-end."""
from pathlib import Path

from lib.manifest import parse_manifest, validate_manifest

DEMO = Path(__file__).parent.parent / "config" / "manifests" / "demo_delegate.yaml"


def test_demo_manifest_parses_with_tiers():
    m = parse_manifest(str(DEMO))
    assert m.project == "demo-delegate"
    tiers = {t.name: (t.model, t.escalation) for t in m.tasks}
    assert tiers["greeting"] == ("haiku", "sonnet")
    assert tiers["word_count"] == ("sonnet", "fable")
    assert validate_manifest(m) == []
