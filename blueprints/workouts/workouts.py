"""
workouts Blueprint - workout logs embedded in each member document (sub-documents).

    GET    /api/v1.0/members/<id>/workouts                 list (date range, type, paging)
    POST   /api/v1.0/members/<id>/workouts                 log a workout
    GET    /api/v1.0/members/<id>/workouts/<workout_id>    one workout
    PUT    /api/v1.0/members/<id>/workouts/<workout_id>    update some fields
    DELETE /api/v1.0/members/<id>/workouts/<workout_id>    delete
All routes: the member themself or an admin.
"""

from bson import ObjectId
from flask import Blueprint

from blueprints.members.members import find_member
from decorators import jwt_required
from globals import exercises, members
from utils.constants import WORKOUT_TYPES
from utils.errors import ApiError
from utils.pagination import PAGINATION_QUERY, facet_envelope, facet_page
from utils.responses import created, no_content, ok
from utils.validation import now_utc, parse_object_id, validate_body, validate_query

workouts_bp = Blueprint("workouts", __name__)

EXERCISE_ENTRY_SCHEMA = {
    "exercise_id": {"type": "objectid", "required": True},
    "sets": {"type": "int", "required": True, "min": 1, "max": 20},
    "reps": {"type": "int", "required": True, "min": 1, "max": 100},
    "weight_kg": {"type": "number", "nullable": True, "min": 0, "max": 500},
}

WORKOUT_SCHEMA = {
    "date": {"type": "datetime", "required": True},
    "workout_type": {"type": "string", "required": True, "choices": WORKOUT_TYPES},
    "duration_min": {"type": "int", "required": True, "min": 1, "max": 300},
    "calories_burned": {"type": "int", "required": True, "min": 0, "max": 5000},
    "avg_bpm": {"type": "int", "required": True, "min": 40, "max": 220},
    "max_bpm": {"type": "int", "required": True, "min": 40, "max": 230},
    "exercises": {"type": "list", "max_items": 30,
                  "items": {"type": "object", "schema": EXERCISE_ENTRY_SCHEMA}},
}


def _check_rules(workout):
    """Checks that involve more than one field or the current time."""
    errors = {}
    if workout.get("date") and workout["date"] > now_utc():
        errors["date"] = "A workout cannot be logged in the future"
    if workout.get("avg_bpm") and workout.get("max_bpm") and workout["max_bpm"] < workout["avg_bpm"]:
        errors["max_bpm"] = "Must be greater than or equal to avg_bpm"
    if errors:
        raise ApiError(400, "Validation failed", errors)


def _resolve_exercises(entries):
    """Looks up every exercise_id in one query and copies in its title."""
    ids = [e["exercise_id"] for e in entries]
    titles = {e["_id"]: e["title"] for e in exercises.find({"_id": {"$in": ids}}, {"title": 1})}
    missing = {f"exercises[{i}].exercise_id": "No exercise exists with this id"
               for i, e in enumerate(entries) if e["exercise_id"] not in titles}
    if missing:
        raise ApiError(400, "Validation failed", missing)
    return [{"exercise_id": e["exercise_id"], "title": titles[e["exercise_id"]],
             "sets": e["sets"], "reps": e["reps"], "weight_kg": e.get("weight_kg")}
            for e in entries]


def _find_workout(member_id, workout_id):
    member = find_member(member_id, {"_id": 1})
    wid = parse_object_id(workout_id, "workout id")
    doc = members.find_one({"_id": member["_id"], "workouts._id": wid}, {"workouts.$": 1})
    if not doc:
        raise ApiError(404, "Workout not found")
    return member["_id"], doc["workouts"][0]


@workouts_bp.route("/members/<id>/workouts", methods=["GET"])
@jwt_required
def list_workouts(id):
    member = find_member(id, {"_id": 1})
    args = validate_query({
        "from": {"type": "datetime"},
        "to": {"type": "datetime"},
        "type": {"type": "list", "items": {"type": "string", "choices": WORKOUT_TYPES}},
        "sort": {"type": "string", "choices": ["newest", "oldest"], "default": "newest"},
        **PAGINATION_QUERY,
    })
    if "from" in args and "to" in args and args["from"] > args["to"]:
        raise ApiError(400, "Invalid query parameters", {"from": "Must be before 'to'"})

    workout_match = {}
    if "from" in args or "to" in args:
        workout_match["date"] = {}
        if "from" in args:
            workout_match["date"]["$gte"] = args["from"]
        if "to" in args:
            workout_match["date"]["$lte"] = args["to"]
    if "type" in args:
        workout_match["workout_type"] = {"$in": args["type"]}

    pipeline = [
        {"$match": {"_id": member["_id"]}},
        {"$unwind": "$workouts"},
        {"$replaceRoot": {"newRoot": "$workouts"}},
        {"$match": workout_match},
        {"$sort": {"date": -1 if args["sort"] == "newest" else 1}},
        facet_page(args["pn"], args["ps"]),
    ]
    return ok(facet_envelope(list(members.aggregate(pipeline)), args["pn"], args["ps"]))


@workouts_bp.route("/members/<id>/workouts", methods=["POST"])
@jwt_required
def add_workout(id):
    member = find_member(id, {"_id": 1})
    data = validate_body(WORKOUT_SCHEMA)
    _check_rules(data)
    workout = {"_id": ObjectId(), **data,
               "exercises": _resolve_exercises(data.get("exercises", []))}
    members.update_one({"_id": member["_id"]}, {"$push": {"workouts": workout}})
    return created("Workout logged", workout["_id"], "workouts.get_workout",
                   id=member["_id"], workout_id=workout["_id"])


@workouts_bp.route("/members/<id>/workouts/<workout_id>", methods=["GET"])
@jwt_required
def get_workout(id, workout_id):
    return ok(_find_workout(id, workout_id)[1])


@workouts_bp.route("/members/<id>/workouts/<workout_id>", methods=["PUT"])
@jwt_required
def update_workout(id, workout_id):
    member_id, workout = _find_workout(id, workout_id)
    data = validate_body(WORKOUT_SCHEMA, partial=True)
    _check_rules({**workout, **data})              # check against the merged result
    if "exercises" in data:
        data["exercises"] = _resolve_exercises(data["exercises"])
    updates = {f"workouts.$.{field}": value for field, value in data.items()}
    members.update_one({"_id": member_id, "workouts._id": workout["_id"]}, {"$set": updates})
    return ok({"message": "Workout updated", "workout": _find_workout(id, workout_id)[1]})


@workouts_bp.route("/members/<id>/workouts/<workout_id>", methods=["DELETE"])
@jwt_required
def delete_workout(id, workout_id):
    member_id, workout = _find_workout(id, workout_id)
    members.update_one({"_id": member_id}, {"$pull": {"workouts": {"_id": workout["_id"]}}})
    return no_content()
