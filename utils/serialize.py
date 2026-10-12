"""
JSON serialisation for MongoDB types.

Installing MongoJSONProvider on the app means every jsonify() call converts
ObjectId -> "hex string" and datetime -> "2026-10-12T18:00:00Z" automatically,
so routes can return documents straight from pymongo.
"""

from datetime import datetime, timezone

from bson import ObjectId
from flask.json.provider import DefaultJSONProvider


def to_iso(value):
    """Formats a datetime as ISO 8601 in UTC with a trailing Z."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class MongoJSONProvider(DefaultJSONProvider):
    sort_keys = False      # keep fields in the order they are stored / built

    @staticmethod
    def default(obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, datetime):
            return to_iso(obj)
        if isinstance(obj, bytes):          # never expected in output, but never crash on it
            return None
        return DefaultJSONProvider.default(obj)
