"""
Local launcher for the Timetable Generator web UI.

Run with:
    python run.py
or, via the project's venv:
    ../venv/bin/python run.py

Starts the Flask API + SPA on http://localhost:5000 and opens the browser
automatically. Use Ctrl+C to stop.
"""
from __future__ import annotations

import sys
import threading
import time
import webbrowser
from pathlib import Path

# Make sibling imports (api, src.*) work regardless of cwd.
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from api import app  # noqa: E402  (path setup must precede this import)


HOST = "127.0.0.1"
PORT = 5000
URL  = f"http://{HOST}:{PORT}"


def _open_browser_after_boot():
    # Give Flask a moment to start listening before launching the tab.
    time.sleep(1.0)
    try:
        webbrowser.open(URL)
    except Exception:  # noqa: BLE001 — best-effort; user can open manually.
        pass


def main():
    print(f"🌐 Timetable Generator UI starting at {URL}")
    print("   (Ctrl+C to stop)")
    threading.Thread(target=_open_browser_after_boot, daemon=True).start()
    # debug=False + use_reloader=False to avoid double-launch (which would
    # also fire the browser-open twice).
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
