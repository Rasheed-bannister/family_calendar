from flask import Blueprint

google_bp = Blueprint("google", __name__, url_prefix="/google")

from . import routes
