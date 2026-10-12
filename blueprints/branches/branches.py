"""
branches Blueprint - gym branches, nearest-branch search and each branch's timetable.

    GET    /api/v1.0/branches                  list (filter by city, facility, name search)
    POST   /api/v1.0/branches                  create                      (admin)
    GET    /api/v1.0/branches/near             branches within km of a point ($geoNear)
    GET    /api/v1.0/branches/<id>             one branch
    PUT    /api/v1.0/branches/<id>             update some fields          (admin)
    DELETE /api/v1.0/branches/<id>             delete if nothing uses it   (admin)
    GET    /api/v1.0/branches/<id>/classes     upcoming classes at the branch
"""

import re

from flask import Blueprint

from decorators import role_required
from globals import branches, classes, members, users
from utils.constants import WORKOUT_TYPES
from utils.errors import ApiError
from utils.pagination import PAGINATION_QUERY, paginate_find
from utils.responses import created, no_content, ok
from utils.validation import now_utc, parse_object_id, to_dotted, validate_body, validate_query

branches_bp = Blueprint("branches", __name__)

HOURS_RULE = {"type": "string", "required": True, "pattern": r"([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d",
              "pattern_msg": "Use the format HH:MM-HH:MM, e.g. 06:00-22:00"}

BRANCH_SCHEMA = {
    "name": {"type": "string", "required": True, "min_len": 3, "max_len": 80},
    "address": {"type": "object", "required": True, "schema": {
        "area": {"type": "string", "required": True, "max_len": 80},
        "city": {"type": "string", "required": True, "max_len": 80},
        "postcode": {"type": "string", "required": True, "max_len": 8,
                     "pattern": r"[A-Za-z]{1,2}\d[A-Za-z\d]?(\s?\d[A-Za-z]{2})?",
                     "pattern_msg": "Must be a UK postcode or postcode district, e.g. BT1 or BT1 5GS"},
    }},
    "lat": {"type": "number", "required": True, "min": -90, "max": 90},
    "lng": {"type": "number", "required": True, "min": -180, "max": 180},
    "opening_hours": {"type": "object", "required": True, "schema": {
        "weekdays": HOURS_RULE, "weekends": HOURS_RULE}},
    "facilities": {"type": "list", "max_items": 30, "items": {"type": "string", "max_len": 50}},
    "capacity": {"type": "int", "required": True, "min": 1, "max": 1000},
    "phone": {"type": "string", "required": True, "pattern": r"[0-9 +()-]{7,20}",
              "pattern_msg": "Must be 7-20 digits, spaces or + ( ) -"},
}

# For updates the nested objects may also be partial (e.g. just address.city)
UPDATE_SCHEMA = {**BRANCH_SCHEMA,
                 "address": {**BRANCH_SCHEMA["address"], "partial": True},
                 "opening_hours": {**BRANCH_SCHEMA["opening_hours"], "partial": True}}


def _find_branch(branch_id):
    branch = branches.find_one({"_id": parse_object_id(branch_id, "branch id")})
    if not branch:
        raise ApiError(404, "Branch not found")
    return branch


def _name_taken(name, exclude_id=None):
    query = {"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}
    if exclude_id:
        query["_id"] = {"$ne": exclude_id}
    return branches.find_one(query, {"_id": 1}) is not None


def _prepare(data):
    """Turns validated input into document fields: lat/lng become a GeoJSON Point."""
    if "lat" in data or "lng" in data:
        if "lat" not in data or "lng" not in data:
            raise ApiError(400, "Validation failed", {"lat/lng": "Send lat and lng together"})
        # GeoJSON order is [longitude, latitude]
        data["location"] = {"type": "Point", "coordinates": [data.pop("lng"), data.pop("lat")]}
    if "postcode" in data.get("address", {}):
        data["address"]["postcode"] = data["address"]["postcode"].upper()
    return data


@branches_bp.route("/branches", methods=["GET"])
def list_branches():
    args = validate_query({
        "city": {"type": "string", "max_len": 80},
        "facility": {"type": "list", "items": {"type": "string"}},
        "q": {"type": "string", "max_len": 80},
        **PAGINATION_QUERY,
    })
    query = {}
    if "city" in args:
        query["address.city"] = {"$regex": f"^{re.escape(args['city'])}$", "$options": "i"}
    if "facility" in args:
        # every requested facility must be present (case-insensitive)
        query["facilities"] = {"$all": [re.compile(f"^{re.escape(f)}$", re.I) for f in args["facility"]]}
    if "q" in args:
        pattern = {"$regex": re.escape(args["q"]), "$options": "i"}
        query["$or"] = [{"name": pattern}, {"address.area": pattern}]
    return ok(paginate_find(branches, query, args["pn"], args["ps"], sort=[("name", 1)]))


@branches_bp.route("/branches", methods=["POST"])
@role_required("admin")
def create_branch():
    data = _prepare(validate_body(BRANCH_SCHEMA))
    if _name_taken(data["name"]):
        raise ApiError(409, "A branch with this name already exists")
    data.setdefault("facilities", [])
    data["created_at"] = now_utc()
    new_id = branches.insert_one(data).inserted_id
    return created("Branch created", new_id, "branches.get_branch", id=new_id)


@branches_bp.route("/branches/near", methods=["GET"])
def branches_near():
    args = validate_query({
        "lat": {"type": "number", "required": True, "min": -90, "max": 90},
        "lng": {"type": "number", "required": True, "min": -180, "max": 180},
        "km": {"type": "number", "min": 0, "max": 100, "default": 10},
        "limit": {"type": "int", "min": 1, "max": 50, "default": 10},
    })
    pipeline = [
        # $geoNear must be the first stage; it uses the 2dsphere index on location
        # and returns documents nearest first, adding the distance in metres.
        {"$geoNear": {
            "near": {"type": "Point", "coordinates": [args["lng"], args["lat"]]},
            "distanceField": "distance_m",
            "maxDistance": args["km"] * 1000,
            "spherical": True,
        }},
        {"$limit": args["limit"]},
        {"$addFields": {"distance_km": {"$round": [{"$divide": ["$distance_m", 1000]}, 2]}}},
        {"$project": {"distance_m": 0}},
    ]
    results = list(branches.aggregate(pipeline))
    return ok({"data": results, "count": len(results),
               "search": {"lat": args["lat"], "lng": args["lng"], "km": args["km"]}})


@branches_bp.route("/branches/<id>", methods=["GET"])
def get_branch(id):
    return ok(_find_branch(id))


@branches_bp.route("/branches/<id>", methods=["PUT"])
@role_required("admin")
def update_branch(id):
    branch = _find_branch(id)
    data = _prepare(validate_body(UPDATE_SCHEMA, partial=True))
    if "name" in data and _name_taken(data["name"], exclude_id=branch["_id"]):
        raise ApiError(409, "A branch with this name already exists")

    # location and facilities are replaced whole; address / opening_hours per sub-field
    location = data.pop("location", None)
    updates = to_dotted(data)
    if location:
        updates["location"] = location
    branches.update_one({"_id": branch["_id"]}, {"$set": updates})

    # Classes keep a copy of the branch name, so keep those copies in step
    if "name" in data:
        classes.update_many({"branch_id": branch["_id"]}, {"$set": {"branch_name": data["name"]}})
    return ok({"message": "Branch updated", "branch": branches.find_one({"_id": branch["_id"]})})


@branches_bp.route("/branches/<id>", methods=["DELETE"])
@role_required("admin")
def delete_branch(id):
    branch = _find_branch(id)
    in_use = {
        "members": members.count_documents({"home_branch_id": branch["_id"]}),
        "trainers": users.count_documents({"role": "trainer", "branch_id": branch["_id"]}),
        "upcoming_classes": classes.count_documents(
            {"branch_id": branch["_id"], "status": "scheduled", "start_time": {"$gt": now_utc()}}),
    }
    if any(in_use.values()):
        raise ApiError(409, "Branch is still in use and cannot be deleted",
                       {k: f"{v} linked" for k, v in in_use.items() if v})
    branches.delete_one({"_id": branch["_id"]})
    return no_content()


@branches_bp.route("/branches/<id>/classes", methods=["GET"])
def branch_classes(id):
    branch = _find_branch(id)
    args = validate_query({
        "category": {"type": "list", "items": {"type": "string", "choices": WORKOUT_TYPES}},
        **PAGINATION_QUERY,
    })
    query = {"branch_id": branch["_id"], "status": "scheduled", "start_time": {"$gt": now_utc()}}
    if "category" in args:
        query["category"] = {"$in": args["category"]}
    page = paginate_find(classes, query, args["pn"], args["ps"],
                         projection={"bookings": 0}, sort=[("start_time", 1)])
    for c in page["data"]:
        c["spaces_left"] = c["capacity"] - c["booked_count"]
    return ok({"branch": {"_id": branch["_id"], "name": branch["name"]}, **page})
