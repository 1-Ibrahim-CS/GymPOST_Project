import logging

from flask import Flask, jsonify, make_response
from flask_cors import CORS
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import HTTPException

from globals import blacklist
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

app = Flask(__name__)
app.json = MongoJSONProvider(app)     # ObjectId and datetime -> JSON strings
CORS(app)

app.register_blueprint(auth_bp)
app.register_blueprint(branches_bp)
app.register_blueprint(exercises_bp)
app.register_blueprint(reviews_bp)
app.register_blueprint(members_bp)
app.register_blueprint(workouts_bp)
app.register_blueprint(classes_bp)
app.register_blueprint(bookings_bp)
app.register_blueprint(reports_bp)

# MongoDB deletes each logged-out token once its expiry time has passed
blacklist.create_index("expires_at", expireAfterSeconds=0)


@app.route("/", methods=["GET"])
def index():
    return make_response("<h1>PulseFit Gym API</h1>", 200)


# ERROR HANDLERS - every error is returned as JSON {"error": ..., "details": ...}
@app.errorhandler(404)
def not_found(e):
    return make_response(jsonify({"error": "Resource not found",
                                  "details": {"description": "The requested URL does not exist on this API"}}), 404)


@app.errorhandler(405)
def method_not_allowed(e):
    return make_response(jsonify({"error": "Method not allowed",
                                  "details": {"allowed_methods": sorted(e.valid_methods or [])}}), 405)


# any other HTTP error Flask raises, e.g. malformed JSON -> 400
@app.errorhandler(HTTPException)
def http_error(e):
    return make_response(jsonify({"error": e.name, "details": {"description": e.description}}), e.code)


# unique index on username / email hit by two requests at the same time
@app.errorhandler(DuplicateKeyError)
def duplicate_key(e):
    key_value = (e.details or {}).get("keyValue") or {"value": None}
    field = list(key_value)[0]
    return make_response(jsonify({"error": "A record with this " + field + " already exists"}), 409)


@app.errorhandler(Exception)
def server_error(e):
    logging.exception("Unhandled error")
    return make_response(jsonify({"error": "Internal server error",
                                  "details": {"description": "Something went wrong on the server"}}), 500)


if __name__ == "__main__":
    app.run(debug=True)
