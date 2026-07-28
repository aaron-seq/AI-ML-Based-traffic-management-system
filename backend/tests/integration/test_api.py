"""HTTP API integration tests.

These drive the real ASGI app through the full middleware stack. The detector is
stubbed so the suite runs in under a second and needs no model weights; every
other service is the genuine article.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.models.traffic_models import (
    LaneDirection,
    LaneStatistics,
    VehicleDetectionResult,
)


class StubDetector:
    """A detector that returns a fixed result without loading any weights."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def is_ready(self) -> bool:
        return True

    async def analyze_intersection_image(self, path: str, **_: Any) -> VehicleDetectionResult:
        self.calls.append(path)
        return VehicleDetectionResult(
            detection_id="det_stub",
            total_vehicles=6,
            lane_counts={
                LaneDirection.NORTH: 4,
                LaneDirection.SOUTH: 1,
                LaneDirection.EAST: 1,
                LaneDirection.WEST: 0,
            },
            lane_statistics={
                LaneDirection.NORTH: LaneStatistics(
                    lane=LaneDirection.NORTH, vehicle_count=4, passenger_car_units=5.0
                )
            },
            processing_time=0.05,
            source="image",
            image_path=path,
        )

    def get_performance_metrics(self) -> dict[str, Any]:
        return {"total_detections": len(self.calls)}

    async def cleanup(self) -> None:
        pass


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A test client with the app's real lifespan run and the detector stubbed."""
    from app.main import app
    from app.services.container import container

    with TestClient(app) as test_client:
        container.detector = StubDetector()  # type: ignore[assignment]
        container.startup_errors.pop("vehicle_detector", None)
        yield test_client


@pytest.fixture
def secured_client(client: TestClient, signal_plan_defaults) -> Iterator[TestClient]:
    """A client whose backend requires an API key on write endpoints."""
    settings.api_key = "test-key-abc123"
    yield client
    settings.api_key = ""


AUTH = {"X-API-Key": "test-key-abc123"}


# --------------------------------------------------------------------------- #
# System
# --------------------------------------------------------------------------- #
class TestSystemEndpoints:
    def test_root_advertises_the_api_surface(self, client):
        body = client.get("/").json()
        assert body["api"] == "/api/v1"
        assert body["websocket"] == "/ws/traffic-updates"

    def test_health_reports_every_service(self, client):
        body = client.get("/health").json()

        assert body["status"] in {"healthy", "degraded", "unhealthy"}
        names = {service["name"] for service in body["services"]}
        assert {"traffic_network", "analytics", "forecast", "impact"} <= names

    def test_health_is_also_available_under_the_versioned_prefix(self, client):
        assert client.get("/api/v1/health").status_code == 200

    def test_system_info_lists_live_capabilities(self, client):
        features = client.get("/api/v1/system/info").json()["features"]

        assert features["adaptive_signal_control"] is True
        assert features["pedestrian_priority"] is True
        assert "green_wave" in features

    def test_configuration_audit_passes_in_the_testing_profile(self, client):
        body = client.get("/api/v1/system/configuration").json()
        assert body["valid"] is True
        assert body["problems"] == []

    def test_metrics_are_exposed_in_prometheus_format(self, client):
        response = client.get("/metrics")

        assert response.status_code == 200
        assert "traffic_signal_phase_changes_total" in response.text

    def test_openapi_schema_is_served(self, client):
        schema = client.get("/api/openapi.json").json()
        assert "/api/v1/detection/image" in schema["paths"]


# --------------------------------------------------------------------------- #
# Intersections
# --------------------------------------------------------------------------- #
class TestIntersectionEndpoints:
    def test_lists_the_default_intersection(self, client):
        rows = client.get("/api/v1/intersections").json()
        assert any(row["intersection_id"] == "main_intersection" for row in rows)

    def test_returns_live_status(self, client):
        body = client.get("/api/v1/intersections/main_intersection").json()

        assert set(body["traffic_signals"]) == {"north", "south", "east", "west"}
        assert body["current_phase"]
        assert "congestion_level" in body

    def test_unknown_intersection_returns_404_with_guidance(self, client):
        response = client.get("/api/v1/intersections/nope")

        assert response.status_code == 404
        assert "GET /api/v1/intersections" in response.json()["detail"]

    def test_manual_counts_drive_the_controller(self, client):
        response = client.post(
            "/api/v1/intersections/main_intersection/counts",
            json={"counts": {"north": 9, "south": 2, "east": 1, "west": 0}},
        )

        assert response.status_code == 200
        assert response.json()["vehicle_counts"]["north"] == 9

    def test_negative_counts_are_rejected(self, client):
        response = client.post(
            "/api/v1/intersections/main_intersection/counts",
            json={"counts": {"north": -5}},
        )
        assert response.status_code == 422

    def test_registers_and_removes_an_intersection(self, client):
        created = client.post(
            "/api/v1/intersections",
            json={"intersection_id": "elm_st", "name": "Elm Street", "distance_from_previous_metres": 300},
        )
        assert created.status_code == 201

        duplicate = client.post(
            "/api/v1/intersections", json={"intersection_id": "elm_st", "name": "Elm Street"}
        )
        assert duplicate.status_code == 409

        assert client.delete("/api/v1/intersections/elm_st").status_code == 204

    def test_the_default_intersection_cannot_be_removed(self, client):
        response = client.delete("/api/v1/intersections/main_intersection")
        assert response.status_code == 400

    def test_coordination_plan_describes_the_corridor(self, client):
        body = client.get("/api/v1/intersections/coordination").json()

        assert "offsets_seconds" in body
        assert body["offsets_seconds"]["main_intersection"] == 0.0

    def test_plan_updates_are_applied(self, client, signal_plan_defaults):
        response = client.patch(
            "/api/v1/intersections/main_intersection/plan",
            json={"minimum_green_duration": 12, "adaptive_mode": True},
        )

        assert response.status_code == 200
        assert response.json()["applied"]["minimum_green_duration"] == 12

    def test_an_inconsistent_plan_is_rejected(self, client, signal_plan_defaults):
        response = client.patch(
            "/api/v1/intersections/main_intersection/plan",
            json={"minimum_green_duration": 300, "maximum_green_duration": 20},
        )
        assert response.status_code == 422

    def test_controller_can_be_stopped_and_started(self, client):
        assert client.post("/api/v1/intersections/main_intersection/stop").json()["running"] is False
        assert client.post("/api/v1/intersections/main_intersection/start").json()["running"] is True


# --------------------------------------------------------------------------- #
# Emergency
# --------------------------------------------------------------------------- #
class TestEmergencyEndpoints:
    def test_override_succeeds_and_returns_the_alert(self, client):
        """This request returned 500 with ``'dict' object has no attribute
        'alert_id'`` before the controller was given a validated model."""
        response = client.post(
            "/api/v1/emergency/override",
            json={"emergency_type": "ambulance", "detected_lane": "north", "priority_level": 5},
        )

        assert response.status_code == 202
        body = response.json()
        assert body["alert_id"].startswith("emg_")
        assert body["is_active"] is True

    def test_the_pre_empted_approach_gets_green(self, client):
        client.post(
            "/api/v1/emergency/override",
            json={"emergency_type": "fire_truck", "detected_lane": "east"},
        )
        status = client.get("/api/v1/intersections/main_intersection").json()

        assert status["emergency_mode_active"] is True
        assert status["traffic_signals"]["east"]["current_state"] == "green"
        assert status["traffic_signals"]["north"]["current_state"] == "red"

    def test_a_supplied_alert_id_is_honoured(self, client):
        body = client.post(
            "/api/v1/emergency/override",
            json={"alert_id": "custom-1", "emergency_type": "police", "detected_lane": "west"},
        ).json()
        assert body["alert_id"] == "custom-1"

    def test_an_unknown_emergency_type_is_rejected(self, client):
        response = client.post(
            "/api/v1/emergency/override",
            json={"emergency_type": "spaceship", "detected_lane": "north"},
        )
        assert response.status_code == 422

    def test_a_missing_field_is_rejected_with_detail(self, client):
        response = client.post("/api/v1/emergency/override", json={"detected_lane": "north"})

        assert response.status_code == 422
        assert response.json()["errors"]

    def test_active_alerts_can_be_listed_and_cleared(self, client):
        alert_id = client.post(
            "/api/v1/emergency/override",
            json={"emergency_type": "ambulance", "detected_lane": "south"},
        ).json()["alert_id"]

        assert any(a["alert_id"] == alert_id for a in client.get("/api/v1/emergency/active").json())
        assert client.delete(f"/api/v1/emergency/override/{alert_id}").json()["cleared"] is True

    def test_clearing_an_unknown_alert_returns_404(self, client):
        assert client.delete("/api/v1/emergency/override/ghost").status_code == 404

    def test_override_for_an_unknown_intersection_returns_404(self, client):
        response = client.post(
            "/api/v1/emergency/override",
            json={
                "emergency_type": "ambulance",
                "detected_lane": "north",
                "intersection_id": "nowhere",
            },
        )
        assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Pedestrians
# --------------------------------------------------------------------------- #
class TestPedestrianEndpoints:
    def test_a_crossing_request_is_accepted(self, client):
        response = client.post(
            "/api/v1/pedestrians/request",
            json={"crossing": "north", "pedestrian_count": 3, "accessibility_extension": True},
        )

        assert response.status_code == 202
        body = response.json()
        assert body["pedestrian_count"] == 3
        assert body["served_at"] is None

    def test_pending_requests_are_listed(self, client):
        client.post("/api/v1/pedestrians/request", json={"crossing": "east"})
        assert len(client.get("/api/v1/pedestrians/pending").json()) >= 1

    def test_the_policy_is_documented_over_the_api(self, client):
        body = client.get("/api/v1/pedestrians/policy").json()

        assert body["crossing_duration_seconds"] > 0
        assert body["accessibility_duration_seconds"] > body["crossing_duration_seconds"]

    def test_a_zero_pedestrian_request_is_rejected(self, client):
        response = client.post(
            "/api/v1/pedestrians/request", json={"crossing": "north", "pedestrian_count": 0}
        )
        assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #
class TestDetectionEndpoints:
    def test_analyses_an_uploaded_image(self, client, sample_image):
        with sample_image.open("rb") as handle:
            response = client.post(
                "/api/v1/detection/image",
                files={"image": ("intersection.jpg", handle, "image/jpeg")},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["total_vehicles"] == 6
        assert body["lane_counts"]["north"] == 4

    def test_detection_feeds_the_signal_controller(self, client, sample_image):
        with sample_image.open("rb") as handle:
            client.post(
                "/api/v1/detection/image",
                files={"image": ("intersection.jpg", handle, "image/jpeg")},
            )

        status = client.get("/api/v1/intersections/main_intersection").json()
        assert status["vehicle_counts"]["north"] == 4

    def test_rejects_a_disallowed_extension(self, client):
        response = client.post(
            "/api/v1/detection/image",
            files={"image": ("payload.exe", b"MZ\x90\x00binary", "application/octet-stream")},
        )
        assert response.status_code == 415

    def test_rejects_a_file_whose_content_is_not_an_image(self, client):
        """A renamed non-image must not reach the decoder."""
        response = client.post(
            "/api/v1/detection/image",
            files={"image": ("evil.jpg", b"#!/bin/sh\nrm -rf /\n" * 4, "image/jpeg")},
        )

        assert response.status_code == 415
        assert "content does not match" in response.json()["detail"]

    def test_rejects_an_empty_upload(self, client):
        response = client.post("/api/v1/detection/image", files={"image": ("empty.jpg", b"", "image/jpeg")})
        assert response.status_code == 400

    def test_rejects_an_oversized_upload(self, client, signal_plan_defaults):
        original = settings.max_upload_size_mb
        settings.max_upload_size_mb = 1
        try:
            payload = b"\xff\xd8\xff" + b"\x00" * (2 * 1024 * 1024)
            response = client.post(
                "/api/v1/detection/image", files={"image": ("big.jpg", payload, "image/jpeg")}
            )
            assert response.status_code == 413
        finally:
            settings.max_upload_size_mb = original

    def test_stream_url_scheme_is_validated(self, client):
        response = client.post("/api/v1/detection/stream", params={"stream_url": "file:///etc/passwd"})
        assert response.status_code == 400

    def test_reports_pipeline_performance(self, client):
        body = client.get("/api/v1/detection/performance").json()
        assert body["model"] == settings.model_name


# --------------------------------------------------------------------------- #
# Analytics, forecast, impact
# --------------------------------------------------------------------------- #
class TestAnalyticsEndpoints:
    def test_summary_is_available_immediately(self, client):
        body = client.get("/api/v1/analytics/summary").json()
        assert body["period"] == "current"

    def test_rejects_an_unsupported_period(self, client):
        assert client.get("/api/v1/analytics/summary", params={"period": "decade"}).status_code == 422

    def test_history_returns_a_bounded_window(self, client):
        body = client.get("/api/v1/analytics/history", params={"hours": 1, "limit": 10}).json()
        assert body["count"] <= 10

    def test_forecast_explains_itself_when_history_is_thin(self, client):
        body = client.get("/api/v1/forecast/main_intersection").json()
        assert body["points"] == [] or body["confidence"] >= 0

    def test_forecast_for_an_unknown_intersection_returns_404(self, client):
        assert client.get("/api/v1/forecast/nowhere").status_code == 404

    def test_impact_includes_its_assumptions(self, client):
        body = client.get("/api/v1/impact/main_intersection").json()

        assert "assumptions" in body
        assert "caveat" in body["assumptions"]
        assert body["currency"] == settings.impact_currency

    def test_cumulative_impact_includes_a_projection(self, client):
        body = client.get("/api/v1/impact/main_intersection/cumulative").json()
        assert "cumulative" in body and "projection" in body


# --------------------------------------------------------------------------- #
# Cross-cutting behaviour
# --------------------------------------------------------------------------- #
class TestMiddlewareBehaviour:
    def test_security_headers_are_present(self, client):
        headers = client.get("/api/v1/intersections").headers

        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert "Content-Security-Policy" in headers

    def test_every_response_carries_a_request_id(self, client):
        assert client.get("/api/v1/intersections").headers["X-Request-ID"]

    def test_an_inbound_request_id_is_preserved_for_tracing(self, client):
        response = client.get("/api/v1/intersections", headers={"X-Request-ID": "trace-me"})
        assert response.headers["X-Request-ID"] == "trace-me"

    def test_errors_include_the_request_id(self, client):
        body = client.get("/api/v1/intersections/missing").json()
        assert "request_id" in body

    def test_obvious_scanner_traffic_is_blocked(self, client):
        assert client.get("/api/v1/../../etc/passwd").status_code in {403, 404}
        assert client.get("/api/v1/intersections", headers={"User-Agent": "sqlmap/1.7"}).status_code == 403

    def test_unknown_paths_return_a_structured_404(self, client):
        body = client.get("/api/v1/does-not-exist").json()
        assert body["detail"]
        assert body["path"] == "/api/v1/does-not-exist"


class TestApiKeyEnforcement:
    def test_reads_stay_open_when_a_key_is_configured(self, secured_client):
        assert secured_client.get("/api/v1/intersections").status_code == 200
        assert secured_client.get("/health").status_code == 200

    def test_writes_are_rejected_without_a_key(self, secured_client):
        response = secured_client.post(
            "/api/v1/emergency/override",
            json={"emergency_type": "ambulance", "detected_lane": "north"},
        )

        assert response.status_code == 401
        assert "X-API-Key" in response.json()["detail"]

    def test_writes_are_rejected_with_a_wrong_key(self, secured_client):
        response = secured_client.post(
            "/api/v1/pedestrians/request",
            json={"crossing": "north"},
            headers={"X-API-Key": "not-the-key"},
        )
        assert response.status_code == 401

    def test_writes_succeed_with_the_correct_key(self, secured_client):
        response = secured_client.post(
            "/api/v1/pedestrians/request", json={"crossing": "north"}, headers=AUTH
        )
        assert response.status_code == 202

    def test_a_bearer_token_is_also_accepted(self, secured_client):
        response = secured_client.post(
            "/api/v1/pedestrians/request",
            json={"crossing": "south"},
            headers={"Authorization": "Bearer test-key-abc123"},
        )
        assert response.status_code == 202


class TestWebSocket:
    def test_sends_an_immediate_snapshot_on_connect(self, client):
        with client.websocket_connect("/ws/traffic-updates") as websocket:
            message = websocket.receive_json()

            assert message["type"] == "intersection_status"
            assert message["data"]["intersection_id"] == "main_intersection"
            # Timestamps must be JSON strings; sending raw datetimes used to
            # break the socket handler.
            assert isinstance(message["timestamp"], str)

    def test_rejects_a_connection_without_the_api_key(self, secured_client):
        from starlette.websockets import WebSocketDisconnect

        with (
            pytest.raises(WebSocketDisconnect),
            secured_client.websocket_connect("/ws/traffic-updates") as websocket,
        ):
            websocket.receive_json()

    def test_accepts_the_api_key_as_a_query_parameter(self, secured_client):
        with secured_client.websocket_connect("/ws/traffic-updates?token=test-key-abc123") as websocket:
            assert websocket.receive_json()["type"] == "intersection_status"
