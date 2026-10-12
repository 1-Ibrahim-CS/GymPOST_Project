"""
classes Blueprint - the class timetable.

    GET    /api/v1.0/classes          list with filters, sorted by start_time
    POST   /api/v1.0/classes          create                    (admin, trainer)
    GET    /api/v1.0/classes/<id>     one class (without the bookings list)
    PUT    /api/v1.0/classes/<id>     update / cancel           (admin, the class's trainer)
    DELETE /api/v1.0/classes/<id>     delete if no active bookings (admin, the class's trainer)
"""

import re
from datetime import timedelta

from flask import Blueprint, g

from decorators import is_admin, role_required
from globals import branches, classes, users
from utils.constants import CLASS_LEVELS, CLASS_STATUSES, WORKOUT_TYPES
from utils.errors import ApiError
from utils.pagination import PAGINATION_QUERY, paginate_find
from utils.responses import created, no_content, ok
from utils.validation import now_utc, parse_object_id, validate_body, validate_query

classes_bp = Blueprint("classes", __name__)

CLASS_SCHEMA = {
    "title": {"type": "string", "required": True, "min_len": 3, "max_len": 80},
    "category": {"type": "string", "required": True, "choices": WORKOUT_TYPES},
    "description": {"type": "string", "max_len": 500},
    "branch_id": {"type": "objectid", "required": True},
    "trainer_id": {"type": "objectid"},            # trainers default to themselves
    "start_time": {"type": "datetime", "required": True},
    "duration_min": {"type": "int", "required": True, "min": 1, "max": 300},
    "level": {"type": "string", "required": True, "choices": CLASS_LEVELS},
    "capacity": {"type": "int", "required": True, "min": 1, "max": 100},
}
# A class cannot move branch (create a new one instead); status can be changed on update
UPDATE_SCHEMA = {**{k: v for k, v in CLASS_SCHEMA.items() if k != "branch_id"},
                 "status": {"type": "string", "choices": CLASS_STATUSES}}

NO_BOOKINGS = {"bookings": 0}


def find_class(class_id, projection=None):
    """Shared with the bookings Blueprint."""
    cls = classes.find_one({"_id": parse_object_id(class_id, "class id")}, projection)
    if not cls:
        raise ApiError(404, "Class not found")
    return cls


def ensure_can_manage(cls):
    """Admins manage every class; trainers only the classes they teach."""
    if is_admin():
        return
    if g.user["role"] == "trainer" and str(cls["trainer_id"]) == g.user["user_id"]:
        return
    raise ApiError(403, "Only an admin or the class's own trainer can do this")


def _get_trainer(trainer_id):
    trainer = users.find_one({"_id": trainer_id, "role": "trainer"}, {"name": 1})
    if not trainer:
        raise ApiError(400, "Validation failed", {"trainer_id": "No trainer exists with this id"})
    return trainer


def _check_trainer_free(trainer_id, start, duration_min, exclude_id=None):
    """409 if the trainer already teaches a scheduled class that overlaps this time.

    Two time ranges overlap when each one starts before the other ends:
        existing.start < new.end  AND  existing.end > new.start
    existing.end is not stored, so $expr works it out as start_time + duration.
    """
    end = start + timedelta(minutes=duration_min)
    query = {
        "trainer_id": trainer_id,
        "status": "scheduled",
        "start_time": {"$lt": end},
        "$expr": {"$gt": [{"$add": ["$start_time", {"$multiply": ["$duration_min", 60000]}]}, start]},
    }
    if exclude_id:
        query["_id"] = {"$ne": exclude_id}
    clash = classes.find_one(query, {"title": 1, "start_time": 1, "branch_name": 1})
    if clash:
        raise ApiError(409, "The trainer already has a class at this time",
                       {"clashing_class": clash})


def _add_spaces(cls):
    cls["spaces_left"] = max(cls["capacity"] - cls["booked_count"], 0)
    return cls


@classes_bp.route("/classes", methods=["GET"])
def list_classes():
    args = validate_query({
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
        **PAGINATION_QUERY,
    })
    if "from" in args and "to" in args and args["from"] > args["to"]:
        raise ApiError(400, "Invalid query parameters", {"from": "Must be before 'to'"})

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
        # Bookable = scheduled, in the future, and booked_count < capacity.
        # $expr is needed to compare two fields of the same document.
        query["status"] = "scheduled"
        query.setdefault("start_time", {})["$gt"] = now
        query["$expr"] = {"$lt": ["$booked_count", "$capacity"]}

    page = paginate_find(classes, query, args["pn"], args["ps"], projection=NO_BOOKINGS,
                         sort=[("start_time", 1), ("_id", 1)])
    page["data"] = [_add_spaces(c) for c in page["data"]]
    return ok(page)


@classes_bp.route("/classes", methods=["POST"])
@role_required("admin", "trainer")
def create_class():
    data = validate_body(CLASS_SCHEMA)

    if g.user["role"] == "trainer":
        own_id = parse_object_id(g.user["user_id"])
        if data.get("trainer_id", own_id) != own_id:
            raise ApiError(403, "Trainers can only create classes they teach themselves")
        data["trainer_id"] = own_id
    elif "trainer_id" not in data:
        raise ApiError(400, "Validation failed", {"trainer_id": "This field is required"})

    errors = {}
    if data["start_time"] <= now_utc():
        errors["start_time"] = "Must be in the future"
    branch = branches.find_one({"_id": data["branch_id"]}, {"name": 1})
    if not branch:
        errors["branch_id"] = "No branch exists with this id"
    if errors:
        raise ApiError(400, "Validation failed", errors)
    trainer = _get_trainer(data["trainer_id"])
    _check_trainer_free(data["trainer_id"], data["start_time"], data["duration_min"])

    doc = {
        "title": data["title"],
        "category": data["category"],
        "description": data.get("description") or
        f"{data['title']} is a {data['duration_min']}-minute {data['category'].lower()} class "
        f"for {data['level'].lower()} members.",
        "branch_id": branch["_id"],
        "branch_name": branch["name"],          # copied so listings need no lookup
        "trainer_id": trainer["_id"],
        "trainer_name": trainer["name"],
        "start_time": data["start_time"],
        "duration_min": data["duration_min"],
        "level": data["level"],
        "capacity": data["capacity"],
        "booked_count": 0,
        "status": "scheduled",
        "bookings": [],
    }
    new_id = classes.insert_one(doc).inserted_id
    return created("Class created", new_id, "classes.get_class", id=new_id)


@classes_bp.route("/classes/<id>", methods=["GET"])
def get_class(id):
    return ok(_add_spaces(find_class(id, NO_BOOKINGS)))


@classes_bp.route("/classes/<id>", methods=["PUT"])
@role_required("admin", "trainer")
def update_class(id):
    cls = find_class(id, NO_BOOKINGS)
    ensure_can_manage(cls)
    data = validate_body(UPDATE_SCHEMA, partial=True)
    now = now_utc()

    if cls["status"] == "cancelled":
        raise ApiError(400, "A cancelled class cannot be changed")
    if "trainer_id" in data and not is_admin() and data["trainer_id"] != cls["trainer_id"]:
        raise ApiError(403, "Only an admin can reassign a class to another trainer")
    if "start_time" in data and data["start_time"] <= now:
        raise ApiError(400, "Validation failed", {"start_time": "Must be in the future"})
    if "capacity" in data and data["capacity"] < cls["booked_count"]:
        raise ApiError(409, "Capacity cannot be lower than the number of places already booked",
                       {"booked_count": cls["booked_count"]})
    if data.get("status") == "completed" and cls["start_time"] > now:
        raise ApiError(400, "A class cannot be completed before it has started")
    if data.get("status") == "scheduled" and cls["status"] == "completed":
        raise ApiError(400, "A completed class cannot be rescheduled")

    updates = dict(data)
    if "trainer_id" in data:
        updates["trainer_name"] = _get_trainer(data["trainer_id"])["name"]
    if {"trainer_id", "start_time", "duration_min"} & data.keys():
        _check_trainer_free(data.get("trainer_id", cls["trainer_id"]),
                            data.get("start_time", cls["start_time"]),
                            data.get("duration_min", cls["duration_min"]), exclude_id=cls["_id"])

    if data.get("status") == "cancelled":
        # Cancel every active booking in the same update that cancels the class
        updates["booked_count"] = 0
        updates["bookings.$[b].status"] = "cancelled"
        classes.update_one({"_id": cls["_id"]}, {"$set": updates},
                           array_filters=[{"b.status": "booked"}])
        message = f"Class cancelled; {cls['booked_count']} booking(s) cancelled"
    else:
        classes.update_one({"_id": cls["_id"]}, {"$set": updates})
        message = "Class updated"
    return ok({"message": message, "class": _add_spaces(find_class(id, NO_BOOKINGS))})


@classes_bp.route("/classes/<id>", methods=["DELETE"])
@role_required("admin", "trainer")
def delete_class(id):
    cls = find_class(id, NO_BOOKINGS)
    ensure_can_manage(cls)
    if cls["status"] == "scheduled" and cls["booked_count"] > 0:
        raise ApiError(409, "This class has active bookings",
                       {"booked_count": cls["booked_count"],
                        "hint": "Cancel it first with PUT {\"status\": \"cancelled\"}"})
    classes.delete_one({"_id": cls["_id"]})
    return no_content()
