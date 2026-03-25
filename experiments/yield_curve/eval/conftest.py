import pytest
from datetime import date
from agora.schemas import TimeSeries, TimeSeriesMetadata


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Emit [METRIC] test_pass_rate for the experiment harness."""
    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))
    total = passed + failed
    rate = passed / total if total > 0 else 0.0
    print(f"\n[METRIC] test_pass_rate={rate:.4f}")


@pytest.fixture
def sample_yields():
    """Normal upward-sloping yield curve data."""
    maturities = {
        "1-Month": 4.5,
        "3-Month": 4.7,
        "6-Month": 4.8,
        "1-Year": 4.6,
        "2-Year": 4.3,
        "5-Year": 4.1,
        "10-Year": 4.2,
        "30-Year": 4.5,
    }
    return [
        TimeSeries(
            date=date(2024, 1, 15),
            value=rate,
            metadata=TimeSeriesMetadata(
                source="TREASURY",
                unit=maturity,
                frequency="Daily",
            ),
        )
        for maturity, rate in maturities.items()
    ]


@pytest.fixture
def inverted_yields():
    """Inverted yield curve data (short rates > long rates)."""
    maturities = {
        "2-Year": 5.0,
        "5-Year": 4.5,
        "10-Year": 4.2,
        "30-Year": 4.4,
    }
    return [
        TimeSeries(
            date=date(2024, 1, 15),
            value=rate,
            metadata=TimeSeriesMetadata(
                source="TREASURY",
                unit=maturity,
                frequency="Daily",
            ),
        )
        for maturity, rate in maturities.items()
    ]


@pytest.fixture
def multi_date_yields():
    """Yield data across multiple dates for spread computation."""
    data = []
    for d, ten_yr, two_yr in [
        (date(2024, 1, 1), 4.0, 4.5),
        (date(2024, 1, 2), 4.1, 4.4),
        (date(2024, 1, 3), 4.2, 4.2),
        (date(2024, 1, 4), 4.3, 4.1),
    ]:
        data.append(TimeSeries(date=d, value=ten_yr, metadata=TimeSeriesMetadata(source="TREASURY", unit="10-Year", frequency="Daily")))
        data.append(TimeSeries(date=d, value=two_yr, metadata=TimeSeriesMetadata(source="TREASURY", unit="2-Year", frequency="Daily")))
    return data
