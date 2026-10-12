"""
Standard error handling.

Every error leaves the API in the same shape:
    {"error": "<short message>", "details": {...optional field errors}}

Routes raise ApiError instead of building responses, and the handlers registered
here turn it (and Flask's own 404/405/500 errors) into JSON.
"""

import logging

from flask import jsonify, make_response
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    """Raised anywhere in a request to stop processing and return an error response."""

    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details


def error_response(status, message, details=None):
    body = {"error": message}
    if details:
        body["details"] = details
    return make_response(jsonify(body), status)


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.status, e.message, e.details)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response(404, "Resource not found",
                              {"description": "The requested URL does not exist on this API"})

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        allowed = sorted(getattr(e, "valid_methods", None) or [])
        return error_response(405, "Method not allowed", {"allowed_methods": allowed})

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Any other HTTP error Flask raises (e.g. malformed JSON -> 400)
        return error_response(e.code, e.name, {"description": e.description})

    @app.errorhandler(DuplicateKeyError)
    def handle_duplicate(e):
        # Safety net for unique indexes (username, email) if two requests race each other
        field = next(iter((e.details or {}).get("keyValue", {}) or {"value": None}))
        return error_response(409, f"A record with this {field} already exists")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        logging.exception("Unhandled error")
        return error_response(500, "Internal server error",
                              {"description": "Something went wrong on the server"})
