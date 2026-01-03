import time

import micropip
from pyodide.http import pyfetch

# Resolve the latest released version from PyPI and install the wheel by direct URL.
# This avoids cached/simple-index responses causing micropip to miss the wheel.
url = f"https://pypi.org/pypi/justhtml/json?cachebust={int(time.time() * 1000)}"
resp = await pyfetch(url, cache="no-store")  # noqa: F704, PLE1142
data = await resp.json()  # noqa: F704, PLE1142
version = data["info"]["version"]

files = data.get("releases", {}).get(version, [])
wheel_url = None
for f in files:
    if f.get("packagetype") == "bdist_wheel" and f.get("filename", "").endswith(".whl"):
        wheel_url = f.get("url")
        break

if not wheel_url:
    raise RuntimeError(f"No wheel found on PyPI for justhtml {version}")

await micropip.install(wheel_url)  # noqa: F704, PLE1142
