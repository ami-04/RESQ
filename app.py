"""RESQ — Blackout Station. Local Flask app (offline-first).

Start:  python app.py          (then open http://127.0.0.1:5000)
Setup:  python manage.py --help
"""
from __future__ import annotations

import logging
import sys

from flask import Flask

from backend.phone import ChallengeBoard
from backend.routes import bp
from backend.station import Station
from backend.storage import LockError
from backend.sync import ApiClient
from config import Config, load_config


def create_app(cfg: Config | None = None, *, station: Station | None = None,
               api: ApiClient | None = None) -> Flask:
    cfg = cfg or load_config()
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["JSON_AS_ASCII"] = False
    app.json.ensure_ascii = False
    app.config["RESQ_CONFIG"] = cfg
    app.config["STATION"] = station or Station.open(cfg)
    app.config["API"] = api or ApiClient(cfg.api_base, cfg.team_token)
    board = ChallengeBoard(ttl_s=cfg.phone_challenge_ttl_s)
    app.config["BOARD"] = board
    app.config["STATION"].phone = board
    app.register_blueprint(bp)

    @app.after_request
    def _headers(resp):
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'")
        return resp

    return app


def main() -> int:
    cfg = load_config()
    try:
        app = create_app(cfg)
    except LockError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    st = app.config["STATION"]
    print(f"RESQ station {st.station_id or '(not initialised)'} · mode {cfg.mode} · data {cfg.data_dir}")
    print(f"Open http://{cfg.host}:{cfg.port}")
    # Werkzeug's access log only shows method + path; request bodies (names, codes) are never logged.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app.run(host=cfg.host, port=cfg.port, debug=False, threaded=True, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
