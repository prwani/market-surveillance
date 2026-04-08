"""
Playwright E2E tests for the Market Surveillance Dashboard.

Tests the live deployment at Azure Container Apps.
Run: python -m pytest tests/test_dashboard_e2e.py -v
"""

import os
import json

import pytest
from playwright.sync_api import sync_playwright, expect

BASE_URL = os.environ.get(
    "DASHBOARD_URL",
    "https://mktsurveil-agent-dev.calmglacier-ce5ee8dd.southeastasia.azurecontainerapps.io",
)


@pytest.fixture(scope="module")
def browser_context():
    """Module-scoped browser context shared across all tests."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(base_url=BASE_URL)
        context.set_default_timeout(15_000)
        yield context
        context.close()
        browser.close()


@pytest.fixture(scope="module")
def page(browser_context):
    """Module-scoped page so simulation state persists for later tests."""
    pg = browser_context.new_page()
    yield pg
    pg.close()


# ── 1. Homepage ──────────────────────────────────────────────────────────


def test_homepage_loads(page):
    """Navigate to / and verify title, nav links, and dashboard cards."""
    page.goto("/")
    assert "Market Surveillance" in page.title()

    nav = page.locator("nav")
    for label in ["Dashboard", "Simulate", "Alerts", "Cases", "KQL"]:
        expect(nav.locator(f"a:has-text('{label}')")).to_be_visible()

    cards = page.locator(".card")
    expect(cards).to_have_count(4)
    for label in ["Total Events", "Active Alerts", "Open Cases", "Reports Generated"]:
        expect(page.locator(f".card .label:has-text('{label}')")).to_be_visible()


# ── 2. Health endpoint ───────────────────────────────────────────────────


def test_health_endpoint(page):
    """/healthz returns {"status": "healthy"}."""
    resp = page.request.get(f"{BASE_URL}/healthz")
    assert resp.status == 200
    body = resp.json()
    assert body["status"] == "healthy"


# ── 3. Ready endpoint ───────────────────────────────────────────────────


def test_ready_endpoint(page):
    """/ready returns 200."""
    resp = page.request.get(f"{BASE_URL}/ready")
    assert resp.status == 200
    body = resp.json()
    assert body["status"] == "ready"


# ── 4. Simulate page ────────────────────────────────────────────────────


def test_simulate_page_loads(page):
    """Verify /simulate has form elements and manipulation toggles."""
    page.goto("/simulate")
    expect(page.locator("h1")).to_contain_text("Simulation")

    expect(page.locator("#exchanges")).to_be_visible()
    expect(page.locator("#duration")).to_be_visible()
    expect(page.locator("#runBtn")).to_be_visible()

    for toggle_id in ["spoofing", "layering", "wash_trading"]:
        expect(page.locator(f"#{toggle_id}")).to_be_visible()


# ── 5. Run simulation (main workflow) ────────────────────────────────────


def test_run_simulation(page):
    """Fill the simulation form and run it, then verify results appear."""
    page.goto("/simulate")

    page.locator("#exchanges").fill("SGX")
    page.locator("#duration").fill("60")

    for cb_id in ["spoofing", "layering", "wash_trading"]:
        cb = page.locator(f"#{cb_id}")
        if not cb.is_checked():
            cb.check()

    page.locator("#runBtn").click()

    # Simulation can take a while; wait for the result pre block to appear
    result = page.locator("#result")
    expect(result.locator("pre")).to_be_visible(timeout=60_000)

    result_text = result.inner_text()
    for keyword in ["event_count", "alert_count", "case_count"]:
        assert keyword in result_text.lower(), (
            f"Expected '{keyword}' in simulation results"
        )


# ── 6. Alerts page after simulation ─────────────────────────────────────


def test_alerts_page_after_simulation(page):
    """Alerts table should have rows with the expected columns."""
    page.goto("/alerts")
    expect(page.locator("h1")).to_contain_text("Alerts")

    headers = page.locator("thead th")
    header_texts = [h.inner_text().upper() for h in headers.all()]
    for col in ["TYPE", "SEVERITY", "EXCHANGE", "SYMBOL", "CONFIDENCE"]:
        assert col in header_texts, f"Column '{col}' not found in {header_texts}"

    rows = page.locator("tbody tr")
    assert rows.count() > 0, "Expected at least one alert row"

    page_text = page.locator("tbody").inner_text().upper()
    assert "SPOOFING" in page_text, "Expected at least one SPOOFING alert"


# ── 7. Cases page after simulation ──────────────────────────────────────


def test_cases_page_after_simulation(page):
    """Cases table should show case rows with statuses."""
    page.goto("/cases")
    expect(page.locator("h1")).to_contain_text("Cases")

    rows = page.locator("tbody tr")
    assert rows.count() > 0, "Expected at least one case row"

    badges = page.locator("tbody .badge")
    assert badges.count() > 0, "Expected case status badges"


# ── 8. KQL page ─────────────────────────────────────────────────────────


def test_kql_page_loads(page):
    """KQL page has a query textarea and a run button."""
    page.goto("/kql")
    expect(page.locator("h1")).to_contain_text("KQL")

    expect(page.locator("#query")).to_be_visible()
    expect(page.locator("#kqlBtn")).to_be_visible()


# ── 9. Navigation ───────────────────────────────────────────────────────


def test_navigation_between_pages(page):
    """Click through every nav link and confirm each page loads."""
    routes = {
        "Dashboard": "/",
        "Simulate": "/simulate",
        "Alerts": "/alerts",
        "Cases": "/cases",
        "KQL": "/kql",
    }
    page.goto("/")
    for label, path in routes.items():
        page.locator(f"nav a:has-text('{label}')").click()
        page.wait_for_url(f"**{path}")
        expect(page.locator("h1")).to_be_visible()

    # Return to dashboard
    page.locator("nav a:has-text('Dashboard')").click()
    page.wait_for_url("**/")
    assert "Dashboard" in page.title()


# ── 10. API /api/simulate ───────────────────────────────────────────────


def test_api_simulate_endpoint(page):
    """POST to /api/simulate and verify the JSON response."""
    payload = {
        "exchanges": ["SGX"],
        "duration": 30,
        "inject_spoofing": True,
        "inject_layering": True,
        "inject_wash_trading": True,
        "inject_price_anomaly": False,
    }
    resp = page.request.post(
        f"{BASE_URL}/api/simulate",
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 200
    data = resp.json()
    assert "event_count" in data, f"Missing 'event_count' in {list(data.keys())}"
    assert "alert_count" in data, f"Missing 'alert_count' in {list(data.keys())}"
    assert "case_count" in data, f"Missing 'case_count' in {list(data.keys())}"
    assert data["event_count"] > 0, f"Expected events > 0, got {data['event_count']}"


# ── 11. API /api/alerts ─────────────────────────────────────────────────


def test_api_alerts_endpoint(page):
    """GET /api/alerts returns a JSON array of alerts."""
    resp = page.request.get(f"{BASE_URL}/api/alerts")
    assert resp.status == 200
    data = resp.json()
    assert isinstance(data, list), f"Expected list, got {type(data)}"
    assert len(data) > 0, "Expected at least one alert"


# ── 12. API /api/stats ──────────────────────────────────────────────────


def test_api_stats_endpoint(page):
    """GET /api/stats returns JSON with stats fields."""
    resp = page.request.get(f"{BASE_URL}/api/stats")
    assert resp.status == 200
    data = resp.json()
    assert "total_events" in data
    assert "total_alerts" in data
    assert "total_cases" in data
