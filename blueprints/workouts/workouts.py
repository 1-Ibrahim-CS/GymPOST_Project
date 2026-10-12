import math

from bson import ObjectId
from flask import Blueprint, g, jsonify, make_response, request

from decorators import jwt_required
from globals import exercises, members
from utils.constants import PAGINATION_QUERY, WORKOUT_TYPES
from utils.validation import now_utc, validate_body, validate_query

workouts_bp = Blueprint("workouts", __name__)

# workouts are stored inside each member document - every route is for the member themself or an admin

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


# checks that need more than one field (or the current time)
def check_workout_rules(workout):
    errors = {}
    if workout.get("date") and workout["date"] > now_utc():
        errors["date"] = "A workout cannot be logged in the future"
    if workout.get("avg_bpm") and workout.get("max_bpm") and workout["max_bpm"] < workout["avg_bpm"]:
        errors["max_bpm"] = "Must be greater than or equal to avg_bpm"
    return errors


# looks up every exercise_id in one query and copies in its title
def add_exercise_titles(entries):
    ids = [entry["exercise_id"] for entry in entries]
    titles = {}
    for exercise in exercises.find({"_id": {"$in": ids}}, {"title": 1}):
        titles[exercise["_id"]] = exercise["title"]

    errors = {}
    resolved = []
    for i, entry in enumerate(entries):
        if entry["exercise_id"] not in titles:
            errors["exercises[" + str(i) + "].exercise_id"] = "No exercise exists with this id"
        else:
            resolved.append({"exercise_id": entry["exercise_id"], "title": titles[entry["exercise_id"]],
                             "sets": entry["sets"], "reps": entry["reps"], "weight_kg": entry.get("weight_kg")})
    return resolved, errors


@workouts_bp.route("/api/v1.0/members/<string:id>/workouts", methods=["GET"])
@jwt_required
def show_all_workouts(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid member ID"}), 400)
    if g.user["role"] != "admin" and g.user["member_id"] != str(ObjectId(id)):
        return make_response(jsonify({"error": "You can only access your own member record"}), 403)
    member = members.find_one({"_id": ObjectId(id)}, {"_id": 1})
    if member is None:
        return make_response(jsonify({"error": "Member not found"}), 404)

    args, errors = validate_query({
        "from": {"type": "datetime"},
        "to": {"type": "datetime"},
        "type": {"type": "list", "items": {"type": "string", "choices": WORKOUT_TYPES}},
        "sort": {"type": "string", "choices": ["newest", "oldest"], "default": "newest"},
        **PAGINATION_QUERY
    })
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)
    if "from" in args and "to" in args and args["from"] > args["to"]:
        return make_response(jsonify({"error": "Invalid query parameters",
                                      "details": {"from": "Must be before 'to'"}}), 400)

    workout_match = {}
    if "from" in args or "to" in args:
        workout_match["date"] = {}
        if "from" in args:
            workout_match["date"]["$gte"] = args["from"]
        if "to" in args:
            workout_match["date"]["$lte"] = args["to"]
    if "type" in args:
        workout_match["workout_type"] = {"$in": args["type"]}

    page_start = args["ps"] * (args["pn"] - 1)
    pipeline = [
        {"$match": {"_id": member["_id"]}},
        {"$unwind": "$workouts"},
        {"$replaceRoot": {"newRoot": "$workouts"}},
        {"$match": workout_match},
        {"$sort": {"date": -1 if args["sort"] == "newest" else 1}},
        {"$facet": {"data": [{"$skip": page_start}, {"$limit": args["ps"]}],
                    "total": [{"$count": "count"}]}}
    ]
    result = list(members.aggregate(pipeline))[0]
    total = result["total"][0]["count"] if result["total"] else 0
    pagination = {"page": args["pn"], "page_size": args["ps"], "total": total,
                  "pages": math.ceil(total / args["ps"])}
    return make_response(jsonify({"data": result["data"], "pagination": pagination}), 200)


@workouts_bp.route("/api/v1.0/members/<string:id>/workouts", methods=["POST"])
@jwt_required
def add_new_workout(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid member ID"}), 400)
    if g.user["role"] != "admin" and g.user["member_id"] != str(ObjectId(id)):
        return make_response(jsonify({"error": "You can only access your own member record"}), 403)
    member = members.find_one({"_id": ObjectId(id)}, {"_id": 1})
    if member is None:
        return make_response(jsonify({"error": "Member not found"}), 404)

    data, errors = validate_body(WORKOUT_SCHEMA)
    if not errors:
        errors = check_workout_rules(data)
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)

    workout_exercises, errors = add_exercise_titles(data.get("exercises", []))
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)

    new_workout = {"_id": ObjectId(), **data, "exercises": workout_exercises}
    members.update_one({"_id": member["_id"]}, {"$push": {"workouts": new_workout}})

    new_workout_link = request.host_url + "api/v1.0/members/" + id + "/workouts/" + str(new_workout["_id"])
    response = make_response(jsonify({"message": "Workout logged", "id": str(new_workout["_id"]),
                                    "url": new_workout_link}), 201)
    response.headers["Location"] = new_workout_link
    return response


@workouts_bp.route("/api/v1.0/members/<string:id>/workouts/<string:workout_id>", methods=["GET"])
@jwt_required
def show_one_workout(id, workout_id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid member ID"}), 400)
    if g.user["role"] != "admin" and g.user["member_id"] != str(ObjectId(id)):
        return make_response(jsonify({"error": "You can only access your own member record"}), 403)
    if members.find_one({"_id": ObjectId(id)}, {"_id": 1}) is None:
        return make_response(jsonify({"error": "Member not found"}), 404)
    if not ObjectId.is_valid(workout_id):
        return make_response(jsonify({"error": "Invalid workout ID"}), 400)

    # "workouts.$" returns only the workout that matched
    member = members.find_one({"_id": ObjectId(id), "workouts._id": ObjectId(workout_id)}, {"workouts.$": 1})
    if member is None:
        return make_response(jsonify({"error": "Workout not found"}), 404)
    return make_response(jsonify(member["workouts"][0]), 200)


@workouts_bp.route("/api/v1.0/members/<string:id>/workouts/<string:workout_id>", methods=["PUT"])
@jwt_required
def edit_workout(id, workout_id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid member ID"}), 400)
    if g.user["role"] != "admin" and g.user["member_id"] != str(ObjectId(id)):
        return make_response(jsonify({"error": "You can only access your own member record"}), 403)
    if members.find_one({"_id": ObjectId(id)}, {"_id": 1}) is None:
        return make_response(jsonify({"error": "Member not found"}), 404)
    if not ObjectId.is_valid(workout_id):
        return make_response(jsonify({"error": "Invalid workout ID"}), 400)
    member = members.find_one({"_id": ObjectId(id), "workouts._id": ObjectId(workout_id)}, {"workouts.$": 1})
    if member is None:
        return make_response(jsonify({"error": "Workout not found"}), 404)
    workout = member["workouts"][0]

    data, errors = validate_body(WORKOUT_SCHEMA, partial=True)
    if not errors:
        # check the rules against the workout as it will be after the update
        errors = check_workout_rules({**workout, **data})
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)

    if "exercises" in data:
        data["exercises"], errors = add_exercise_titles(data["exercises"])
        if errors:
            return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)

    updates = {}
    for field, value in data.items():
        updates["workouts.$." + field] = value
    members.update_one({"_id": member["_id"], "workouts._id": workout["_id"]}, {"$set": updates})

    member = members.find_one({"_id": member["_id"], "workouts._id": workout["_id"]}, {"workouts.$": 1})
    return make_response(jsonify({"message": "Workout updated", "workout": member["workouts"][0]}), 200)


@workouts_bp.route("/api/v1.0/members/<string:id>/workouts/<string:workout_id>", methods=["DELETE"])
@jwt_required
def delete_workout(id, workout_id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid member ID"}), 400)
    if g.user["role"] != "admin" and g.user["member_id"] != str(ObjectId(id)):
        return make_response(jsonify({"error": "You can only access your own member record"}), 403)
    if members.find_one({"_id": ObjectId(id)}, {"_id": 1}) is None:
        return make_response(jsonify({"error": "Member not found"}), 404)
    if not ObjectId.is_valid(workout_id):
        return make_response(jsonify({"error": "Invalid workout ID"}), 400)

    result = members.update_one({"_id": ObjectId(id), "workouts._id": ObjectId(workout_id)},
                                {"$pull": {"workouts": {"_id": ObjectId(workout_id)}}})
    if result.modified_count == 0:
        return make_response(jsonify({"error": "Workout not found"}), 404)
    return make_response(jsonify({}), 204)
