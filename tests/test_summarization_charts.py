"""Tests for summarization charts no-data handling."""
from pathlib import Path
from unittest.mock import patch
import sys

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestCompressionRatioChart:
    """Tests for chart_compression_ratio function."""

    def test_returns_placeholder_when_no_data(self, tmp_path):
        """Should return placeholder HTML when no summarization data exists."""
        charts_dir = tmp_path / "charts"
        charts_dir.mkdir()

        # Mock empty telemetry
        mock_telemetry = {
            "events": [],
            "aggregates": {}
        }

        with patch('charts.load_telemetry', return_value=mock_telemetry):
            with patch('charts.CHARTS_DIR', charts_dir):
                from charts import chart_compression_ratio
                result = chart_compression_ratio()

        # Should return a valid path, not None
        assert result is not None
        assert Path(result).exists()

        # Should contain helpful message
        content = Path(result).read_text()
        assert "coming soon" in content.lower() or "not yet" in content.lower()

    def test_placeholder_has_back_link(self, tmp_path):
        """Placeholder should have link back to dashboard."""
        charts_dir = tmp_path / "charts"
        charts_dir.mkdir()

        mock_telemetry = {"events": [], "aggregates": {}}

        with patch('charts.load_telemetry', return_value=mock_telemetry):
            with patch('charts.CHARTS_DIR', charts_dir):
                from charts import chart_compression_ratio
                result = chart_compression_ratio()

        content = Path(result).read_text()
        assert "dashboard.html" in content


class TestTokensSavedChart:
    """Tests for chart_tokens_saved function."""

    def test_returns_placeholder_when_no_data(self, tmp_path):
        """Should return placeholder HTML when no summarization data exists."""
        charts_dir = tmp_path / "charts"
        charts_dir.mkdir()

        mock_telemetry = {
            "events": [],
            "aggregates": {}
        }

        with patch('charts.load_telemetry', return_value=mock_telemetry):
            with patch('charts.CHARTS_DIR', charts_dir):
                from charts import chart_tokens_saved
                result = chart_tokens_saved()

        assert result is not None
        assert Path(result).exists()

        content = Path(result).read_text()
        assert "coming soon" in content.lower() or "not yet" in content.lower()


class TestHasSummarizationData:
    """Tests for summarization data detection helper."""

    def test_returns_false_when_no_events_with_full_size(self):
        """Should return False when no events have full_size > 0."""
        from charts import _has_summarization_data

        events = [
            {"tool": "Read", "full_size": 0},
            {"tool": "Write"},  # no full_size key
        ]
        assert _has_summarization_data(events) is False

    def test_returns_true_when_events_have_full_size(self):
        """Should return True when events have full_size > 0."""
        from charts import _has_summarization_data

        events = [
            {"tool": "Read", "full_size": 1000, "summary_size": 200},
        ]
        assert _has_summarization_data(events) is True
