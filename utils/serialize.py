from datetime import datetime, timezone

from bson import ObjectId
from flask.json.provider import DefaultJSONProvider


# datetime -> "2026-10-12T18:00:00Z"
def to_iso(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# installed in app.py so jsonify() turns ObjectId and datetime into strings automatically
class MongoJSONProvider(DefaultJSONProvider):
    sort_keys = False      # keep fields in the order they are stored

    @staticmethod
    def default(obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, datetime):
            return to_iso(obj)
        if isinstance(obj, bytes):
            return None
        return DefaultJSONProvider.default(obj)
