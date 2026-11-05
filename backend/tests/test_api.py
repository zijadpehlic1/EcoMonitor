from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_and_performance_header() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert float(response.headers["X-Process-Time-Ms"]) >= 0


def test_history_endpoint_exposes_grouping_provenance_and_completeness() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/history",
            params={
                "location": "zenica",
                "hours": 24,
                "grouping": "daily",
                "aggregation": "maximum",
            },
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["grouping"] == "daily"
    assert payload["aggregation"] == "maximum"
    assert payload["timezone"] == "Europe/Sarajevo"
    assert payload["pollution_source"]["type"] == "modeled"
    assert "missing samples are not imputed" in payload["completeness_note"]


def test_sensor_dataset_requires_existing_city_owned_station():
    with TestClient(app) as client:
        for path in ('/history', '/forecast/pm25', '/forecast/pm25/weather-comparison'):
            assert client.get('/api/v1' + path, params={'source': 'sensor', 'station_id': 999999}).status_code == 422
        assert client.get('/api/v1/history', params={'source': 'modeled', 'station_id': 1}).status_code == 422
        assert client.get('/api/v1/sensors/stations?location=unknown').status_code == 404

