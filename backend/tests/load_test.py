"""Locust load profile.

Not collected by pytest -- run it directly:

    locust -f tests/load_test.py --headless -u 50 -r 5 -t 2m -H http://localhost:8000

The mix is weighted towards the traffic a real deployment sees: many cheap
status polls from dashboards, a steady trickle of count updates from field
sensors, and occasional operator actions.
"""

from __future__ import annotations

import os
import random

from locust import HttpUser, between, events, task

INTERSECTION_ID = os.getenv("LOAD_TEST_INTERSECTION", "main_intersection")
API_KEY = os.getenv("TRAFFIC_API_KEY", "")
LANES = ("north", "south", "east", "west")


def auth_headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY} if API_KEY else {}


def request(user: HttpUser, method: str, path: str, name: str | None = None, **kwargs) -> None:
    """Issue a request, scoring 429 as backpressure rather than a failure.

    Rate limiting is keyed on client IP, and a load generator is a single IP, so
    it trips the limiter long before the server is actually saturated. A 429 is
    the system working correctly -- counting it as an error would make every run
    look like a failure and hide the latency signal that matters.

    To measure real throughput, raise the limits on the target first:

        TRAFFIC_RATE_LIMIT_REQUESTS_PER_MINUTE=100000 \
        TRAFFIC_RATE_LIMIT_UPLOAD_REQUESTS_PER_MINUTE=100000 uvicorn app.main:app
    """
    with user.client.request(method, path, name=name or path, catch_response=True, **kwargs) as response:
        if response.status_code == 429:
            response.success()
        elif response.status_code >= 400:
            response.failure(f"HTTP {response.status_code}")
        else:
            response.success()


class DashboardUser(HttpUser):
    """A control-room display: polls status and analytics, never writes."""

    weight = 6
    wait_time = between(1, 3)

    @task(10)
    def poll_intersection_status(self) -> None:
        self.client.get(f"/api/v1/intersections/{INTERSECTION_ID}", name="/api/v1/intersections/{id}")

    @task(3)
    def poll_health(self) -> None:
        self.client.get("/health")

    @task(2)
    def poll_analytics(self) -> None:
        self.client.get("/api/v1/analytics/summary?period=current", name="/api/v1/analytics/summary")

    @task(1)
    def list_intersections(self) -> None:
        self.client.get("/api/v1/intersections")

    @task(1)
    def read_impact(self) -> None:
        self.client.get(f"/api/v1/impact/{INTERSECTION_ID}", name="/api/v1/impact/{id}")


class FieldSensorUser(HttpUser):
    """A roadside sensor pushing counts on a fixed cadence."""

    weight = 3
    wait_time = between(2, 5)

    @task
    def submit_counts(self) -> None:
        payload = {
            "counts": {lane: random.randint(0, 25) for lane in LANES},
            "intersection_id": INTERSECTION_ID,
        }
        request(
            self,
            "POST",
            f"/api/v1/intersections/{INTERSECTION_ID}/counts",
            "/api/v1/intersections/{id}/counts",
            json=payload,
            headers=auth_headers(),
        )


class OperatorUser(HttpUser):
    """An operator occasionally raising pre-emptions and pedestrian phases."""

    weight = 1
    wait_time = between(10, 30)

    @task(3)
    def request_pedestrian_crossing(self) -> None:
        request(
            self,
            "POST",
            "/api/v1/pedestrians/request",
            json={"crossing": random.choice(LANES), "intersection_id": INTERSECTION_ID},
            headers=auth_headers(),
        )

    @task(1)
    def trigger_emergency_override(self) -> None:
        request(
            self,
            "POST",
            "/api/v1/emergency/override",
            json={
                "emergency_type": random.choice(["ambulance", "fire_truck", "police"]),
                "detected_lane": random.choice(LANES),
                "priority_level": 5,
                "intersection_id": INTERSECTION_ID,
            },
            headers=auth_headers(),
        )


@events.quitting.add_listener
def enforce_service_levels(environment, **_kwargs) -> None:
    """Fail the run when the service level is not met, so CI can gate on it."""
    stats = environment.stats.total

    if stats.num_requests == 0:
        print("FAIL: no requests were made")
        environment.process_exit_code = 1
        return

    failure_ratio = stats.num_failures / stats.num_requests
    p95 = stats.get_response_time_percentile(0.95)

    if failure_ratio > 0.01:
        print(f"FAIL: error rate {failure_ratio:.2%} exceeds the 1% budget")
        environment.process_exit_code = 1
    elif p95 > 1000:
        print(f"FAIL: 95th percentile {p95} ms exceeds the 1000 ms budget")
        environment.process_exit_code = 1
    else:
        print(f"PASS: {stats.num_requests} requests, {failure_ratio:.2%} errors, p95 {p95} ms")
        environment.process_exit_code = 0
