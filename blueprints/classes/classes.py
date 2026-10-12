import math
import re
from datetime import timedelta

from bson import ObjectId
from flask import Blueprint, g, jsonify, make_response, request

from decorators import role_required
from globals import branches, classes, users
from utils.constants import CLASS_LEVELS, CLASS_STATUSES, PAGINATION_QUERY, WORKOUT_TYPES
from utils.validation import now_utc, validate_body, validate_query

classes_bp = Blueprint("classes", __name__)

CLASS_SCHEMA = {
    "title": {"type": "string", "required": True, "min_len": 3, "max_len": 80},
    "category": {"type": "string", "required": True, "choices": WORKOUT_TYPES},
    "description": {"type": "string", "max_len": 500},
    "branch_id": {"type": "objectid", "required": True},
    "trainer_id": {"type": "objectid"},            # a trainer creating a class teaches it themself
    "start_time": {"type": "datetime", "required": True},
    "duration_min": {"type": "int", "required": True, "min": 1, "max": 300},
    "level": {"type": "string", "required": True, "choices": CLASS_LEVELS},
    "capacity": {"type": "int", "required": True, "min": 1, "max": 100},
}

# a class can't move branch, but its status can be changed on PUT
UPDATE_SCHEMA = {}
for field_name, field_rules in CLASS_SCHEMA.items():
    if field_name != "branch_id":
        UPDATE_SCHEMA[field_name] = field_rules
UPDATE_SCHEMA["status"] = {"type": "string", "choices": CLASS_STATUSES}


# another scheduled class the trainer teaches at an overlapping time, or None.
# two times overlap when each one starts before the other ends; the end time
# isn't stored so $expr works it out as start_time + duration
def find_trainer_clash(trainer_id, start, duration_min, exclude_id=None):
    end = start + timedelta(minutes=duration_min)
    query = {
        "trainer_id": trainer_id,
        "status": "scheduled",
        "start_time": {"$lt": end},
        "$expr": {"$gt": [{"$add": ["$start_time", {"$multiply": ["$duration_min", 60000]}]}, start]}
    }
    if exclude_id:
        query["_id"] = {"$ne": exclude_id}
    return classes.find_one(query, {"title": 1, "start_time": 1, "branch_name": 1})


@classes_bp.route("/api/v1.0/classes", methods=["GET"])
def show_all_classes():
    args, errors = validate_query({
        "branch": {"type": "objectid"},
        "trainer": {"type": "objectid"},
        "category": {"type": "list", "items": {"type": "string", "choices": WORKOUT_TYPES}},
        "level": {"type": "list", "items": {"type": "string", "choices": CLASS_LEVELS}},
        "status": {"type": "string", "choices": CLASS_STATUSES},
        "when": {"type": "string", "choices": ["upcoming", "past", "all"], "default": "upcoming"},
        "from": {"type": "datetime"},
        "to": {"type": "datetime"},
        "available": {"type": "bool"},
        "q": {"type": "string", "max_len": 80},
        **PAGINATION_QUERY
    })
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)
    if "from" in args and "to" in args and args["from"] > args["to"]:
        return make_response(jsonify({"error": "Invalid query parameters",
                                      "details": {"from": "Must be before 'to'"}}), 400)

    now = now_utc()
    time_range = {}
    if args["when"] == "upcoming":
        time_range["$gt"] = now
    elif args["when"] == "past":
        time_range["$lte"] = now
    if "from" in args:
        time_range["$gte"] = args["from"]
    if "to" in args:
        time_range["$lte"] = min(args["to"], time_range.get("$lte", args["to"]))

    query = {}
    if time_range:
        query["start_time"] = time_range
    if "branch" in args:
        query["branch_id"] = args["branch"]
    if "trainer" in args:
        query["trainer_id"] = args["trainer"]
    if "category" in args:
        query["category"] = {"$in": args["category"]}
    if "level" in args:
        query["level"] = {"$in": args["level"]}
    if "status" in args:
        query["status"] = args["status"]
    if "q" in args:
        query["title"] = {"$regex": re.escape(args["q"]), "$options": "i"}
    if args.get("available"):
        # bookable = scheduled, in the future and booked_count < capacity
        # ($expr is needed to compare two fields of the same document)
        query["status"] = "scheduled"
        query.setdefault("start_time", {})["$gt"] = now
        query["$expr"] = {"$lt": ["$booked_count", "$capacity"]}

    page_start = args["ps"] * (args["pn"] - 1)
    data = list(classes.find(query, {"bookings": 0}).sort([("start_time", 1), ("_id", 1)])
                .skip(page_start).limit(args["ps"]))
    for cls in data:
        cls["spaces_left"] = max(cls["capacity"] - cls["booked_count"], 0)
    total = classes.count_documents(query)
    pagination = {"page": args["pn"], "page_size": args["ps"], "total": total,
                  "pages": math.ceil(total / args["ps"])}
    return make_response(jsonify({"data": data, "pagination": pagination}), 200)


@classes_bp.route("/api/v1.0/classes", methods=["POST"])
@role_required("admin", "trainer")
def add_new_class():
    data, errors = validate_body(CLASS_SCHEMA)
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)

    if g.user["role"] == "trainer":
        own_id = ObjectId(g.user["user_id"])
        if data.get("trainer_id", own_id) != own_id:
            return make_response(jsonify({"error": "Trainers can only create classes they teach themselves"}), 403)
        data["trainer_id"] = own_id
    elif "trainer_id" not in data:
        return make_response(jsonify({"error": "Validation failed",
                                      "details": {"trainer_id": "This field is required"}}), 400)

    errors = {}
    if data["start_time"] <= now_utc():
        errors["start_time"] = "Must be in the future"
    branch = branches.find_one({"_id": data["branch_id"]}, {"name": 1})
    if branch is None:
        errors["branch_id"] = "No branch exists with this id"
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)

    trainer = users.find_one({"_id": data["trainer_id"], "role": "trainer"}, {"name": 1})
    if trainer is None:
        return make_response(jsonify({"error": "Validation failed",
                                      "details": {"trainer_id": "No trainer exists with this id"}}), 400)

    clash = find_trainer_clash(data["trainer_id"], data["start_time"], data["duration_min"])
    if clash is not None:
        return make_response(jsonify({"error": "The trainer already has a class at this time",
                                      "details": {"clashing_class": clash}}), 409)

    description = data.get("description")
    if not description:
        description = data["title"] + " is a " + str(data["duration_min"]) + "-minute " + \
            data["category"].lower() + " class for " + data["level"].lower() + " members."

    new_class = {
        "title": data["title"],
        "category": data["category"],
        "description": description,
        "branch_id": branch["_id"],
        "branch_name": branch["name"],          # copied so class lists don't need a lookup
        "trainer_id": trainer["_id"],
        "trainer_name": trainer["name"],
        "start_time": data["start_time"],
        "duration_min": data["duration_min"],
        "level": data["level"],
        "capacity": data["capacity"],
        "booked_count": 0,
        "status": "scheduled",
        "bookings": []
    }
    new_id = classes.insert_one(new_class).inserted_id

    new_class_link = request.host_url + "api/v1.0/classes/" + str(new_id)
    response = make_response(jsonify({"message": "Class created", "id": str(new_id), "url": new_class_link}), 201)
    response.headers["Location"] = new_class_link
    return response


@classes_bp.route("/api/v1.0/classes/<string:id>", methods=["GET"])
def show_one_class(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid class ID"}), 400)
    cls = classes.find_one({"_id": ObjectId(id)}, {"bookings": 0})
    if cls is None:
        return make_response(jsonify({"error": "Class not found"}), 404)
    cls["spaces_left"] = max(cls["capacity"] - cls["booked_count"], 0)
    return make_response(jsonify(cls), 200)


# admin or the class's own trainer - also used to cancel a class
@classes_bp.route("/api/v1.0/classes/<string:id>", methods=["PUT"])
@role_required("admin", "trainer")
def edit_class(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid class ID"}), 400)
    cls = classes.find_one({"_id": ObjectId(id)}, {"bookings": 0})
    if cls is None:
        return make_response(jsonify({"error": "Class not found"}), 404)
    is_admin = g.user["role"] == "admin"
    if not is_admin and str(cls["trainer_id"]) != g.user["user_id"]:
        return make_response(jsonify({"error": "Only an admin or the class's own trainer can do this"}), 403)

    data, errors = validate_body(UPDATE_SCHEMA, partial=True)
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)

    now = now_utc()
    if cls["status"] == "cancelled":
        return make_response(jsonify({"error": "A cancelled class cannot be changed"}), 400)
    if "trainer_id" in data and not is_admin and data["trainer_id"] != cls["trainer_id"]:
        return make_response(jsonify({"error": "Only an admin can reassign a class to another trainer"}), 403)
    if "start_time" in data and data["start_time"] <= now:
        return make_response(jsonify({"error": "Validation failed",
                                      "details": {"start_time": "Must be in the future"}}), 400)
    if "capacity" in data and data["capacity"] < cls["booked_count"]:
        return make_response(jsonify({"error": "Capacity cannot be lower than the number of places already booked",
                                      "details": {"booked_count": cls["booked_count"]}}), 409)
    if data.get("status") == "completed" and cls["start_time"] > now:
        return make_response(jsonify({"error": "A class cannot be completed before it has started"}), 400)
    if data.get("status") == "scheduled" and cls["status"] == "completed":
        return make_response(jsonify({"error": "A completed class cannot be rescheduled"}), 400)

    updates = dict(data)
    if "trainer_id" in data:
        trainer = users.find_one({"_id": data["trainer_id"], "role": "trainer"}, {"name": 1})
        if trainer is None:
            return make_response(jsonify({"error": "Validation failed",
                                          "details": {"trainer_id": "No trainer exists with this id"}}), 400)
        updates["trainer_name"] = trainer["name"]

    if "trainer_id" in data or "start_time" in data or "duration_min" in data:
        clash = find_trainer_clash(data.get("trainer_id", cls["trainer_id"]),
                                   data.get("start_time", cls["start_time"]),
                                   data.get("duration_min", cls["duration_min"]),
                                   exclude_id=cls["_id"])
        if clash is not None:
            return make_response(jsonify({"error": "The trainer already has a class at this time",
                                          "details": {"clashing_class": clash}}), 409)

    if data.get("status") == "cancelled":
        # cancel every active booking in the same update that cancels the class
        updates["booked_count"] = 0
        updates["bookings.$[b].status"] = "cancelled"
        classes.update_one({"_id": cls["_id"]}, {"$set": updates}, array_filters=[{"b.status": "booked"}])
        message = "Class cancelled; " + str(cls["booked_count"]) + " booking(s) cancelled"
    else:
        classes.update_one({"_id": cls["_id"]}, {"$set": updates})
        message = "Class updated"

    updated_class = classes.find_one({"_id": cls["_id"]}, {"bookings": 0})
    updated_class["spaces_left"] = max(updated_class["capacity"] - updated_class["booked_count"], 0)
    return make_response(jsonify({"message": message, "class": updated_class}), 200)


# admin or the class's own trainer - only when nobody is booked on it
@classes_bp.route("/api/v1.0/classes/<string:id>", methods=["DELETE"])
@role_required("admin", "trainer")
def delete_class(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid class ID"}), 400)
    cls = classes.find_one({"_id": ObjectId(id)}, {"bookings": 0})
    if cls is None:
        return make_response(jsonify({"error": "Class not found"}), 404)
    if g.user["role"] != "admin" and str(cls["trainer_id"]) != g.user["user_id"]:
        return make_response(jsonify({"error": "Only an admin or the class's own trainer can do this"}), 403)

    if cls["status"] == "scheduled" and cls["booked_count"] > 0:
        return make_response(jsonify({"error": "This class has active bookings",
                                      "details": {"booked_count": cls["booked_count"],
                                                  "hint": "Cancel it first with PUT {\"status\": \"cancelled\"}"}}), 409)

    classes.delete_one({"_id": cls["_id"]})
    return make_response(jsonify({}), 204)
