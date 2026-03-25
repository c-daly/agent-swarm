"""Eval tests for the API routes."""

import pytest


class TestYieldsEndpoint:
    """GET /api/yields returns yield time series data."""

    def test_yields_returns_200(self, client):
        resp = client.get("/api/yields")
        assert resp.status_code == 200

    def test_yields_returns_list(self, client):
        resp = client.get("/api/yields")
        data = resp.json()
        assert isinstance(data, list)

    def test_yields_with_maturities_filter(self, client):
        resp = client.get("/api/yields", params={"maturities": "10yr,2yr"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_yields_with_date_range(self, client):
        resp = client.get(
            "/api/yields",
            params={"start_date": "2024-01-01", "end_date": "2024-03-31"},
        )
        assert resp.status_code == 200

    def test_yields_items_have_required_fields(self, client):
        resp = client.get("/api/yields")
        data = resp.json()
        if len(data) > 0:
            item = data[0]
            assert "date" in item
            assert "value" in item


class TestYieldCurveEndpoint:
    """GET /api/yields/curve returns the latest yield curve."""

    def test_curve_returns_200(self, client):
        resp = client.get("/api/yields/curve")
        assert resp.status_code == 200

    def test_curve_returns_list(self, client):
        resp = client.get("/api/yields/curve")
        data = resp.json()
        assert isinstance(data, list)

    def test_curve_items_have_maturity_and_yield(self, client):
        resp = client.get("/api/yields/curve")
        data = resp.json()
        if len(data) > 0:
            item = data[0]
            assert "maturity" in item
            assert "yield" in item or "value" in item


class TestSpreadEndpoint:
    """GET /api/yields/spread returns the spread time series."""

    def test_spread_returns_200(self, client):
        resp = client.get("/api/yields/spread")
        assert resp.status_code == 200

    def test_spread_returns_list(self, client):
        resp = client.get("/api/yields/spread")
        data = resp.json()
        assert isinstance(data, list)

    def test_spread_items_have_date_and_spread(self, client):
        resp = client.get("/api/yields/spread")
        data = resp.json()
        if len(data) > 0:
            item = data[0]
            assert "date" in item
            assert "spread" in item or "value" in item

    def test_spread_custom_maturities(self, client):
        resp = client.get(
            "/api/yields/spread", params={"long": "30yr", "short": "5yr"}
        )
        assert resp.status_code == 200


class TestInversionsEndpoint:
    """GET /api/yields/inversions returns inversion periods."""

    def test_inversions_returns_200(self, client):
        resp = client.get("/api/yields/inversions")
        assert resp.status_code == 200

    def test_inversions_returns_list(self, client):
        resp = client.get("/api/yields/inversions")
        data = resp.json()
        assert isinstance(data, list)


class TestFtdEndpoint:
    """GET /api/ftd returns fails-to-deliver data."""

    def test_ftd_requires_symbol(self, client):
        resp = client.get("/api/ftd")
        assert resp.status_code in (400, 422)

    def test_ftd_with_symbol_returns_200(self, client):
        resp = client.get("/api/ftd", params={"symbol": "GME"})
        assert resp.status_code == 200

    def test_ftd_returns_list(self, client):
        resp = client.get("/api/ftd", params={"symbol": "GME"})
        data = resp.json()
        assert isinstance(data, list)

    def test_ftd_items_have_required_fields(self, client):
        resp = client.get("/api/ftd", params={"symbol": "GME"})
        data = resp.json()
        if len(data) > 0:
            item = data[0]
            assert "date" in item
            assert "value" in item or "quantity" in item


class TestFredEndpoint:
    """GET /api/fred returns FRED series data."""

    def test_fred_requires_series_id(self, client):
        resp = client.get("/api/fred")
        assert resp.status_code in (400, 422)

    def test_fred_with_series_id_returns_200(self, client):
        resp = client.get("/api/fred", params={"series_id": "GDP"})
        assert resp.status_code == 200

    def test_fred_returns_list(self, client):
        resp = client.get("/api/fred", params={"series_id": "GDP"})
        data = resp.json()
        assert isinstance(data, list)

    def test_fred_items_have_required_fields(self, client):
        resp = client.get("/api/fred", params={"series_id": "GDP"})
        data = resp.json()
        if len(data) > 0:
            item = data[0]
            assert "date" in item
            assert "value" in item


class TestGlossaryEndpoints:
    """GET /api/glossary and GET /api/glossary/{term}."""

    def test_glossary_returns_200(self, client):
        resp = client.get("/api/glossary")
        assert resp.status_code == 200

    def test_glossary_returns_dict_or_list(self, client):
        resp = client.get("/api/glossary")
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_glossary_term_returns_200(self, client):
        # First get all terms, then look up one
        resp = client.get("/api/glossary")
        data = resp.json()
        if isinstance(data, dict) and len(data) > 0:
            term_key = next(iter(data))
            resp2 = client.get(f"/api/glossary/{term_key}")
            assert resp2.status_code == 200
        elif isinstance(data, list) and len(data) > 0:
            first = data[0]
            term_key = first.get("term", first.get("key", "yield_curve"))
            resp2 = client.get(f"/api/glossary/{term_key}")
            assert resp2.status_code == 200

    def test_glossary_unknown_term_returns_404(self, client):
        resp = client.get("/api/glossary/definitely_not_a_real_term_xyz")
        assert resp.status_code == 404


class TestErrorHandling:
    """Routes return proper error responses."""

    def test_json_content_type(self, client):
        resp = client.get("/api/yields")
        assert "application/json" in resp.headers.get("content-type", "")

    def test_404_returns_json_body(self, client):
        resp = client.get("/api/glossary/nonexistent_term_xyz123")
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data or "error" in data or "message" in data
