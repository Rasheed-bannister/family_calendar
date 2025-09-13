from flask import Blueprint

google_bp = Blueprint("google", __name__, url_prefix="/google")

from . import (  # noqa: F401,E402 # Required for route registration after blueprint creation
    routes,
)
