"""
app.py - entry point for the PulseFit Gym and Fitness Class Booking API.

Creates the Flask app, installs the MongoDB-aware JSON encoder and the JSON error
handlers, and registers one Blueprint per resource under /api/v1.0.

Run with:  python app.py   (serves on http://127.0.0.1:5000)
"""

from flask import Flask
from flask_cors import CORS

from globals import blacklist
from utils.errors import register_error_handlers
from utils.serialize import MongoJSONProvider

from blueprints.auth.auth import auth_bp
from blueprints.branches.branches import branches_bp
from blueprints.exercises.exercises import exercises_bp
from blueprints.reviews.reviews import reviews_bp
from blueprints.members.members import members_bp
from blueprints.workouts.workouts import workouts_bp
from blueprints.classes.classes import classes_bp
from blueprints.bookings.bookings import bookings_bp
from blueprints.reports.reports import reports_bp

API_PREFIX = "/api/v1.0"

BLUEPRINTS = [auth_bp, branches_bp, exercises_bp, reviews_bp, members_bp, workouts_bp,
              classes_bp, bookings_bp, reports_bp]


def ensure_indexes():
    """Indexes the API relies on that seed.py does not create (create_index is idempotent)."""
    # TTL index: MongoDB deletes each blacklisted token once its expiry time has passed
    blacklist.create_index("expires_at", expireAfterSeconds=0)


def create_app():
    app = Flask(__name__)
    app.json = MongoJSONProvider(app)     # ObjectId / datetime -> JSON
    CORS(app)                             # allow a front end on another origin to call the API
    register_error_handlers(app)
    for bp in BLUEPRINTS:
        app.register_blueprint(bp, url_prefix=API_PREFIX)
    ensure_indexes()
    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
