"""WSGI entrypoint, e.g. ``waitress-serve --threads 16 wsgi:app``.

Starts the same process-level runtime the ``python -m src.main`` path does,
so a WSGI server gets the PIR sensor, display service and background sync
rather than a fully wired API with nothing behind it.
"""

from src.main import create_app
from src.runtime import start_runtime

app = create_app()
start_runtime(app)
