"""Offline by default; database and model checks require explicit opt-in."""
import pytest


def pytest_addoption(parser):
    parser.addoption("--integration", action="store_true", help="Allow configured database/API credentials")
    parser.addoption("--models", action="store_true", help="Run face-model tests (may download weights)")


def pytest_configure(config):
    config.addinivalue_line("markers", "models: requires installed face models and may download weights")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--models"):
        for item in items:
            if item.get_closest_marker("models"):
                item.add_marker(pytest.mark.skip(reason="Pass --models to run real face-model checks"))


@pytest.fixture(autouse=True, scope="session")
def offline_credentials(request):
    # Run before module-scoped database fixtures, including when the shell has .env loaded.
    with pytest.MonkeyPatch.context() as patch:
        if not request.config.getoption("--integration"):
            for key in ("DATABASE_URL", "MODEL_API_KEY", "SERPAPI_KEY"):
                patch.delenv(key, raising=False)
        yield
