"""Browser UI test (opt-in): RESQ_UI_TESTS=1 pytest tests/test_ui.py
Needs `pip install playwright` and either `playwright install chromium` or RESQ_CHROME=/path/to/chrome."""
import os
import threading

import pytest

if os.environ.get("RESQ_UI_TESTS") != "1":
    pytest.skip("UI tests are opt-in (set RESQ_UI_TESTS=1)", allow_module_level=True)

playwright = pytest.importorskip("playwright.sync_api")
from werkzeug.serving import make_server  # noqa: E402

from app import create_app  # noqa: E402
from backend.sync import ApiClient  # noqa: E402


@pytest.fixture
def server(station):
    app = create_app(station.cfg, station=station, api=ApiClient("https://x.invalid", None))
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_operator_flows_in_browser(server, station):
    with playwright.sync_playwright() as p:
        kw = {"executable_path": os.environ["RESQ_CHROME"]} if os.environ.get("RESQ_CHROME") else {}
        b = p.chromium.launch(args=["--no-sandbox"], **kw)
        pg = b.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(server + "/")
        pg.fill("#code", "3nw4uj"); pg.press("#code", "Enter")
        pg.wait_for_selector("#feedback.success")
        pg.fill("#code", "3NW-4UJ"); pg.press("#code", "Enter")
        pg.wait_for_selector("#feedback.rejected")
        pg.fill("#code", "3NW-4UJ"); pg.press("#code", "Shift+Enter")
        pg.wait_for_selector("#feedback.success")
        pg.keyboard.press("F2")
        pg.fill("#w-name", "Ana"); pg.click("[data-role=gruen]"); pg.check("#w-consent"); pg.click("#w-submit")
        pg.wait_for_selector("#w-feedback.success")
        pg.click("#w-decline"); pg.wait_for_selector("#w-feedback.rejected")
        b.close()
    assert not errors
    types = [e["type"] for e in station.log.entries]
    assert types == ["genesis", "checkin", "rejected", "checkout", "walkin", "rejected"]
