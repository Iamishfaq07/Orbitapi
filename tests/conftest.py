"""Integration test harness: boots the core service and the gateway together."""
import os
import socket
import subprocess
import sys
import tempfile
import time

import pytest
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(url):
    for _ in range(100):
        try:
            requests.get(url, timeout=0.5)
            return
        except requests.ConnectionError:
            time.sleep(0.1)
    raise RuntimeError(f"service did not start: {url}")


@pytest.fixture(scope="session")
def services():
    core_port, gw_port = _free_port(), _free_port()
    data = tempfile.mkdtemp(prefix="orbit-test-")
    env = {**os.environ, "ORBIT_DATA_DIR": data,
           "ORBIT_CORE_URL": f"http://127.0.0.1:{core_port}",
           "ORBIT_GATEWAY_URL": f"http://127.0.0.1:{gw_port}"}
    core = subprocess.Popen([sys.executable, "-m", "uvicorn", "service:app", "--port", str(core_port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _wait(f"http://127.0.0.1:{core_port}/health")
    gw = subprocess.Popen([sys.executable, "-m", "uvicorn", "gateway:app", "--port", str(gw_port)],
                          cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _wait(f"http://127.0.0.1:{gw_port}/health")
    yield {"gw": f"http://127.0.0.1:{gw_port}", "core": f"http://127.0.0.1:{core_port}"}
    core.terminate(); gw.terminate()
    core.wait(timeout=5); gw.wait(timeout=5)


@pytest.fixture(autouse=True)
def reset(services):
    requests.post(services["core"] + "/internal/reset")


class Client:
    def __init__(self, services):
        self.gw = services["gw"]
        self._n = 0

    def login(self, username, password):
        self._n += 1
        r = requests.post(self.gw + "/api/v2/auth/login", json={"username": username, "password": password},
                          headers={"X-Forwarded-For": f"10.1.{self._n // 250}.{self._n % 250}"})
        j = r.json()
        if j.get("mfa_required"):
            uid = {"alice": 1, "grace": 7}[username]
            otp = requests.get(self.gw + f"/api/v1/users/{uid}").json()["otp_code"]
            j = requests.post(self.gw + "/api/v2/auth/mfa/verify",
                              json={"username": username, "otp": otp}).json()
        return j["access_token"]

    def get(self, path, token=None, **kw):
        headers = kw.pop("headers", {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return requests.get(self.gw + path, headers=headers, **kw)

    def post(self, path, token=None, **kw):
        headers = kw.pop("headers", {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return requests.post(self.gw + path, headers=headers, **kw)


@pytest.fixture
def client(services):
    return Client(services)
