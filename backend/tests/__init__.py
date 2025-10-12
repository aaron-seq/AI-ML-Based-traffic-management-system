"""
Test package for AI Traffic Management System
Provides comprehensive testing for all components
"""

import pytest
import asyncio
from pathlib import Path

# Test configuration
TEST_DATA_DIR = Path(__file__).parent / "test_data"
TEST_IMAGES_DIR = TEST_DATA_DIR / "images"
TEST_OUTPUTS_DIR = Path(__file__).parent.parent / "test_outputs"

# Ensure test directories exist
TEST_DATA_DIR.mkdir(exist_ok=True)
TEST_IMAGES_DIR.mkdir(exist_ok=True)
TEST_OUTPUTS_DIR.mkdir(exist_ok=True)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def test_image_path():
    """Provide path to test image"""
    return TEST_IMAGES_DIR / "test_intersection.jpg"


@pytest.fixture
def test_output_dir():
    """Provide path to test output directory"""
    return TEST_OUTPUTS_DIR
