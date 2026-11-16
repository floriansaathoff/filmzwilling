from __future__ import annotations

import json
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

SCRIPT = Path(__file__).parent / "e2e" / "rate_flow.mjs"


def playwright_available() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    probe = subprocess.run(
        [node, "-e", "require('playwright').chromium.executablePath()"],
        capture_output=True,
        timeout=30,
    )
    return probe.returncode == 0


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_keyboard_rating_flow(tmp_path: Path) -> None:
    if not playwright_available():
        pytest.skip("Playwright für Node ist nicht installiert")
    import uvicorn

    from filmzwilling.demo import prepare_demo
    from filmzwilling.service import FilmService
    from filmzwilling.web.app import create_app

    settings = prepare_demo(tmp_path / "demo")
    app = create_app(FilmService(settings))
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        result = subprocess.run(
            ["node", str(SCRIPT), f"http://127.0.0.1:{port}"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        info = json.loads(result.stdout.strip().splitlines()[-1])
        assert info["ok"] is True
        assert info["switchMs"] < 1000
    finally:
        server.should_exit = True
        thread.join(timeout=10)
