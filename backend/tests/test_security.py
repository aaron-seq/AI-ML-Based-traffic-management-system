"""Security primitive tests: upload hardening, rate limiting, auth, config."""

from __future__ import annotations

import pytest

from app.core import config as app_config
from app.core.config import ApplicationSettings, ProductionSettings, validate_configuration
from app.core.security import (
    SlidingWindowRateLimiter,
    file_extension,
    generate_secure_filename,
    is_suspicious_request,
    looks_like_image,
    sanitize_filename,
    validate_file_type,
)


class TestFilenameSanitisation:
    @pytest.mark.parametrize(
        "hostile",
        [
            "../../../etc/passwd",
            "..\\..\\windows\\system32\\config",
            "/etc/shadow",
            "....//....//etc/hosts",
            "subdir/nested/file.jpg",
        ],
    )
    def test_strips_every_path_component(self, hostile):
        cleaned = sanitize_filename(hostile)

        assert "/" not in cleaned
        assert "\\" not in cleaned
        assert not cleaned.startswith(".")

    def test_normalises_unicode_lookalikes(self):
        """NFKC folds a fullwidth solidus into '/', which basename alone misses."""
        cleaned = sanitize_filename("evil／..／passwd.jpg")  # noqa: RUF001 - the lookalike is the test
        assert "/" not in cleaned

    def test_replaces_shell_metacharacters(self):
        cleaned = sanitize_filename("photo;rm -rf $HOME.jpg")
        assert all(character not in cleaned for character in ";$ ")

    def test_generates_a_name_for_empty_input(self):
        for value in (None, "", "...", "///"):
            assert sanitize_filename(value)

    def test_caps_the_length(self):
        assert len(sanitize_filename("a" * 5000 + ".jpg")) <= 180

    def test_keeps_ordinary_names_recognisable(self):
        assert sanitize_filename("intersection_01.jpg") == "intersection_01.jpg"


class TestFileTypeValidation:
    def test_extracts_the_extension_case_insensitively(self):
        assert file_extension("photo.JPG") == ".jpg"
        assert file_extension("clip.MP4") == ".mp4"
        assert file_extension("noextension") == ""

    def test_accepts_only_allowed_extensions(self):
        allowed = [".jpg", ".png"]

        assert validate_file_type("a.jpg", allowed) is True
        assert validate_file_type("a.PNG", allowed) is True
        assert validate_file_type("a.exe", allowed) is False
        assert validate_file_type(None, allowed) is False

    def test_double_extensions_are_judged_on_the_last_one(self):
        assert validate_file_type("shell.jpg.php", [".jpg"]) is False

    def test_secure_names_are_unique_but_keep_the_extension(self):
        first = generate_secure_filename("photo.jpg")
        second = generate_secure_filename("photo.jpg")

        assert first != second
        assert first.endswith(".jpg")


class TestImageMagicNumbers:
    @pytest.mark.parametrize(
        "payload",
        [
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x02\x03",  # JPEG
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",  # PNG
            b"BM\x36\x00\x00\x00\x00\x00\x00\x00\x36\x00",  # BMP
            b"RIFF\x24\x00\x00\x00WEBPVP8 ",  # WebP
        ],
    )
    def test_recognises_supported_formats(self, payload):
        assert looks_like_image(payload) is True

    @pytest.mark.parametrize(
        "payload",
        [
            b"#!/bin/sh\necho pwned\n",
            b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00",  # Windows PE
            b"<?php system($_GET[0]); ?>",
            b"",
            b"short",
        ],
    )
    def test_rejects_everything_else(self, payload):
        assert looks_like_image(payload) is False

    def test_riff_that_is_not_webp_is_rejected(self):
        """RIFF also prefixes WAV and AVI; only the WEBP subtype is an image."""
        assert looks_like_image(b"RIFF\x24\x00\x00\x00WAVEfmt ") is False


class TestRateLimiting:
    def test_allows_requests_up_to_the_limit(self):
        limiter = SlidingWindowRateLimiter()

        for _ in range(5):
            allowed, _ = limiter.check("client", limit=5, window_seconds=60)
            assert allowed is True

    def test_blocks_the_request_after_the_limit(self):
        limiter = SlidingWindowRateLimiter()
        for _ in range(3):
            limiter.check("client", limit=3, window_seconds=60)

        allowed, retry_after = limiter.check("client", limit=3, window_seconds=60)

        assert allowed is False
        assert retry_after > 0

    def test_clients_have_independent_budgets(self):
        limiter = SlidingWindowRateLimiter()
        for _ in range(3):
            limiter.check("noisy", limit=3, window_seconds=60)

        allowed, _ = limiter.check("quiet", limit=3, window_seconds=60)
        assert allowed is True

    def test_tracked_clients_are_bounded(self):
        """An unbounded map would be a memory-exhaustion vector under a flood
        of spoofed source addresses."""
        limiter = SlidingWindowRateLimiter(max_tracked_clients=50)

        for index in range(500):
            limiter.check(f"client-{index}", limit=10, window_seconds=60)

        assert len(limiter._windows) <= 50

    def test_reset_clears_all_state(self):
        limiter = SlidingWindowRateLimiter()
        limiter.check("client", limit=1, window_seconds=60)
        limiter.reset()

        allowed, _ = limiter.check("client", limit=1, window_seconds=60)
        assert allowed is True


class TestSuspiciousRequestDetection:
    @pytest.mark.parametrize(
        ("path", "query", "agent"),
        [
            ("/api/../../etc/passwd", "", "curl/8"),
            ("/api/v1/x", "q=<script>alert(1)</script>", "Mozilla"),
            ("/api/v1/x", "id=1 UNION SELECT password", "Mozilla"),
            ("/api/v1/x", "", "sqlmap/1.7"),
            ("/api/v1/x", "", "Nikto/2.5"),
        ],
    )
    def test_flags_known_attack_shapes(self, path, query, agent):
        assert is_suspicious_request(path, query, agent) is True

    @pytest.mark.parametrize(
        ("path", "query", "agent"),
        [
            ("/api/v1/intersections/main_intersection", "", "Mozilla/5.0"),
            ("/api/v1/analytics/summary", "period=hourly", "python-httpx/0.28"),
            ("/health", "", ""),
        ],
    )
    def test_leaves_legitimate_traffic_alone(self, path, query, agent):
        assert is_suspicious_request(path, query, agent) is False


class TestConfiguration:
    def test_the_testing_profile_is_self_consistent(self):
        assert validate_configuration(app_config.TestingSettings()) == []

    def test_flags_an_unsafe_production_configuration(self):
        unsafe = ProductionSettings(allowed_origins=["*"], trusted_hosts=["*"], api_key="", jwt_secret_key="")
        problems = validate_configuration(unsafe)

        assert any("CORS" in problem for problem in problems)
        assert any("TRUSTED_HOSTS" in problem or "trusted host" in problem for problem in problems)
        assert any("API_KEY" in problem for problem in problems)

    def test_a_hardened_production_configuration_passes(self):
        safe = ProductionSettings(
            allowed_origins=["https://traffic.example.gov"],
            trusted_hosts=["traffic.example.gov"],
            api_key="a-long-shared-api-key-value",
            jwt_secret_key="x" * 48,
        )
        assert validate_configuration(safe) == []

    def test_flags_contradictory_green_bounds(self):
        config = ApplicationSettings(minimum_green_duration=90, maximum_green_duration=30)
        assert any("minimum_green_duration" in problem for problem in validate_configuration(config))

    def test_list_settings_accept_comma_separated_strings(self):
        config = ApplicationSettings(allowed_origins="https://a.example, https://b.example")
        assert config.allowed_origins == ["https://a.example", "https://b.example"]

    def test_a_short_jwt_secret_is_rejected(self):
        with pytest.raises(ValueError, match="at least 32"):
            ApplicationSettings(jwt_secret_key="too-short")

    def test_confidence_threshold_must_be_a_probability(self):
        with pytest.raises(ValueError):
            ApplicationSettings(detection_confidence_threshold=1.5)

    def test_database_url_must_look_like_a_url(self):
        with pytest.raises(ValueError, match="SQLAlchemy URL"):
            ApplicationSettings(database_url="just-a-path.db")

    def test_redis_url_scheme_is_validated(self):
        with pytest.raises(ValueError, match="redis://"):
            ApplicationSettings(redis_connection_string="http://localhost:6379")

    def test_derived_helpers_are_consistent(self):
        config = ApplicationSettings(max_upload_size_mb=8, enable_gpu_acceleration=False)

        assert config.max_upload_size_bytes == 8 * 1024 * 1024
        assert config.inference_device == "cpu"
        assert config.is_production is False
