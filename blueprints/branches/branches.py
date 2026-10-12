import math
import re

from bson import ObjectId
from flask import Blueprint, jsonify, make_response, request

from decorators import role_required
from globals import branches, classes, members, users
from utils.constants import PAGINATION_QUERY, WORKOUT_TYPES
from utils.validation import now_utc, to_dotted, validate_body, validate_query

branches_bp = Blueprint("branches", __name__)

HOURS_RULE = {"type": "string", "required": True,
              "pattern": r"([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d",
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

# on PUT the address and opening hours can also be sent in part (e.g. just address.city)
UPDATE_SCHEMA = {**BRANCH_SCHEMA,
                 "address": {**BRANCH_SCHEMA["address"], "partial": True},
                 "opening_hours": {**BRANCH_SCHEMA["opening_hours"], "partial": True}}


@branches_bp.route("/api/v1.0/branches", methods=["GET"])
def show_all_branches():
    args, errors = validate_query({
        "city": {"type": "string", "max_len": 80},
        "facility": {"type": "list", "items": {"type": "string"}},
        "q": {"type": "string", "max_len": 80},
        **PAGINATION_QUERY
    })
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)

    query = {}
    if "city" in args:
        query["address.city"] = {"$regex": "^" + re.escape(args["city"]) + "$", "$options": "i"}
    if "facility" in args:
        # every facility asked for must be there
        query["facilities"] = {"$all": [re.compile("^" + re.escape(f) + "$", re.I) for f in args["facility"]]}
    if "q" in args:
        pattern = {"$regex": re.escape(args["q"]), "$options": "i"}
        query["$or"] = [{"name": pattern}, {"address.area": pattern}]

    page_start = args["ps"] * (args["pn"] - 1)
    data = list(branches.find(query).sort("name", 1).skip(page_start).limit(args["ps"]))
    total = branches.count_documents(query)
    pagination = {"page": args["pn"], "page_size": args["ps"], "total": total,
                  "pages": math.ceil(total / args["ps"])}
    return make_response(jsonify({"data": data, "pagination": pagination}), 200)


@branches_bp.route("/api/v1.0/branches", methods=["POST"])
@role_required("admin")
def add_new_branch():
    data, errors = validate_body(BRANCH_SCHEMA)
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)

    name_query = {"name": {"$regex": "^" + re.escape(data["name"]) + "$", "$options": "i"}}
    if branches.find_one(name_query) is not None:
        return make_response(jsonify({"error": "A branch with this name already exists"}), 409)

    # GeoJSON order is [longitude, latitude]
    data["location"] = {"type": "Point", "coordinates": [data.pop("lng"), data.pop("lat")]}
    data["address"]["postcode"] = data["address"]["postcode"].upper()
    data.setdefault("facilities", [])
    data["created_at"] = now_utc()
    new_id = branches.insert_one(data).inserted_id

    new_branch_link = request.host_url + "api/v1.0/branches/" + str(new_id)
    response = make_response(jsonify({"message": "Branch created", "id": str(new_id), "url": new_branch_link}), 201)
    response.headers["Location"] = new_branch_link
    return response


# branches within km of a point, nearest first
@branches_bp.route("/api/v1.0/branches/near", methods=["GET"])
def show_branches_near():
    args, errors = validate_query({
        "lat": {"type": "number", "required": True, "min": -90, "max": 90},
        "lng": {"type": "number", "required": True, "min": -180, "max": 180},
        "km": {"type": "number", "min": 0, "max": 100, "default": 10},
        "limit": {"type": "int", "min": 1, "max": 50, "default": 10}
    })
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)

    pipeline = [
        # $geoNear has to be the first stage - it uses the 2dsphere index on location
        {"$geoNear": {
            "near": {"type": "Point", "coordinates": [args["lng"], args["lat"]]},
            "distanceField": "distance_m",
            "maxDistance": args["km"] * 1000,
            "spherical": True
        }},
        {"$limit": args["limit"]},
        {"$addFields": {"distance_km": {"$round": [{"$divide": ["$distance_m", 1000]}, 2]}}},
        {"$project": {"distance_m": 0}}
    ]
    results = list(branches.aggregate(pipeline))
    return make_response(jsonify({"data": results, "count": len(results),
                                  "search": {"lat": args["lat"], "lng": args["lng"], "km": args["km"]}}), 200)


@branches_bp.route("/api/v1.0/branches/<string:id>", methods=["GET"])
def show_one_branch(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid branch ID"}), 400)
    branch = branches.find_one({"_id": ObjectId(id)})
    if branch is None:
        return make_response(jsonify({"error": "Branch not found"}), 404)
    return make_response(jsonify(branch), 200)


@branches_bp.route("/api/v1.0/branches/<string:id>", methods=["PUT"])
@role_required("admin")
def edit_branch(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid branch ID"}), 400)
    branch = branches.find_one({"_id": ObjectId(id)})
    if branch is None:
        return make_response(jsonify({"error": "Branch not found"}), 404)

    data, errors = validate_body(UPDATE_SCHEMA, partial=True)
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)
    if ("lat" in data) != ("lng" in data):
        return make_response(jsonify({"error": "Validation failed",
                                      "details": {"lat/lng": "Send lat and lng together"}}), 400)

    if "name" in data:
        name_query = {"name": {"$regex": "^" + re.escape(data["name"]) + "$", "$options": "i"},
                      "_id": {"$ne": branch["_id"]}}
        if branches.find_one(name_query) is not None:
            return make_response(jsonify({"error": "A branch with this name already exists"}), 409)

    location = None
    if "lat" in data:
        location = {"type": "Point", "coordinates": [data.pop("lng"), data.pop("lat")]}
    if "postcode" in data.get("address", {}):
        data["address"]["postcode"] = data["address"]["postcode"].upper()

    # address and opening_hours are updated field by field, location is replaced whole
    updates = to_dotted(data)
    if location:
        updates["location"] = location
    branches.update_one({"_id": branch["_id"]}, {"$set": updates})

    # classes keep a copy of the branch name, so update those too
    if "name" in data:
        classes.update_many({"branch_id": branch["_id"]}, {"$set": {"branch_name": data["name"]}})

    return make_response(jsonify({"message": "Branch updated",
                                  "branch": branches.find_one({"_id": branch["_id"]})}), 200)


# a branch can only be deleted when no members, trainers or upcoming classes use it
@branches_bp.route("/api/v1.0/branches/<string:id>", methods=["DELETE"])
@role_required("admin")
def delete_branch(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid branch ID"}), 400)
    branch = branches.find_one({"_id": ObjectId(id)})
    if branch is None:
        return make_response(jsonify({"error": "Branch not found"}), 404)

    in_use = {
        "members": members.count_documents({"home_branch_id": branch["_id"]}),
        "trainers": users.count_documents({"role": "trainer", "branch_id": branch["_id"]}),
        "upcoming_classes": classes.count_documents(
            {"branch_id": branch["_id"], "status": "scheduled", "start_time": {"$gt": now_utc()}})
    }
    linked = {}
    for name, count in in_use.items():
        if count > 0:
            linked[name] = str(count) + " linked"
    if linked:
        return make_response(jsonify({"error": "Branch is still in use and cannot be deleted",
                                      "details": linked}), 409)

    branches.delete_one({"_id": branch["_id"]})
    return make_response(jsonify({}), 204)


# upcoming classes at one branch
@branches_bp.route("/api/v1.0/branches/<string:id>/classes", methods=["GET"])
def show_branch_classes(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid branch ID"}), 400)
    branch = branches.find_one({"_id": ObjectId(id)})
    if branch is None:
        return make_response(jsonify({"error": "Branch not found"}), 404)

    args, errors = validate_query({
        "category": {"type": "list", "items": {"type": "string", "choices": WORKOUT_TYPES}},
        **PAGINATION_QUERY
    })
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)

    query = {"branch_id": branch["_id"], "status": "scheduled", "start_time": {"$gt": now_utc()}}
    if "category" in args:
        query["category"] = {"$in": args["category"]}

    page_start = args["ps"] * (args["pn"] - 1)
    data = list(classes.find(query, {"bookings": 0}).sort("start_time", 1).skip(page_start).limit(args["ps"]))
    for cls in data:
        cls["spaces_left"] = cls["capacity"] - cls["booked_count"]
    total = classes.count_documents(query)
    pagination = {"page": args["pn"], "page_size": args["ps"], "total": total,
                  "pages": math.ceil(total / args["ps"])}
    return make_response(jsonify({"branch": {"_id": branch["_id"], "name": branch["name"]},
                                  "data": data, "pagination": pagination}), 200)
