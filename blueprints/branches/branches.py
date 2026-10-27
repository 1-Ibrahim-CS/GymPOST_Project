import math
import re

from bson import ObjectId
from flask import Blueprint, jsonify, make_response, request

from decorators import role_required
import globals
from utils.validation import PAGINATION_QUERY, now_utc, to_dotted, validate_body, validate_query

branches_bp = Blueprint("branches", __name__)


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
    data = list(globals.db.branches.find(query).sort("name", 1).skip(page_start).limit(args["ps"]))
    total = globals.db.branches.count_documents(query)
    pagination = {"page": args["pn"], "page_size": args["ps"], "total": total,
                  "pages": math.ceil(total / args["ps"])}
    return make_response(jsonify({"data": data, "pagination": pagination}), 200)


@branches_bp.route("/api/v1.0/branches", methods=["POST"])
@role_required("admin")
def add_new_branch():
    data, errors = validate_body(globals.SCHEMAS["branch_create"])
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)

    name_query = {"name": {"$regex": "^" + re.escape(data["name"]) + "$", "$options": "i"}}
    if globals.db.branches.find_one(name_query) is not None:
        return make_response(jsonify({"error": "A branch with this name already exists"}), 409)

    # GeoJSON order is [longitude, latitude]
    data["location"] = {"type": "Point", "coordinates": [data.pop("lng"), data.pop("lat")]}
    data["address"]["postcode"] = data["address"]["postcode"].upper()
    data.setdefault("facilities", [])
    data["created_at"] = now_utc()
    new_id = globals.db.branches.insert_one(data).inserted_id

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
    results = list(globals.db.branches.aggregate(pipeline))
    return make_response(jsonify({"data": results, "count": len(results),
                                  "search": {"lat": args["lat"], "lng": args["lng"], "km": args["km"]}}), 200)


@branches_bp.route("/api/v1.0/branches/<string:id>", methods=["GET"])
def show_one_branch(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid branch ID"}), 400)
    branch = globals.db.branches.find_one({"_id": ObjectId(id)})
    if branch is None:
        return make_response(jsonify({"error": "Branch not found"}), 404)
    return make_response(jsonify(branch), 200)


@branches_bp.route("/api/v1.0/branches/<string:id>", methods=["PUT"])
@role_required("admin")
def edit_branch(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid branch ID"}), 400)
    branch = globals.db.branches.find_one({"_id": ObjectId(id)})
    if branch is None:
        return make_response(jsonify({"error": "Branch not found"}), 404)

    data, errors = validate_body(globals.SCHEMAS["branch_update"], partial=True)
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)
    if ("lat" in data) != ("lng" in data):
        return make_response(jsonify({"error": "Validation failed",
                                      "details": {"lat/lng": "Send lat and lng together"}}), 400)

    if "name" in data:
        name_query = {"name": {"$regex": "^" + re.escape(data["name"]) + "$", "$options": "i"},
                      "_id": {"$ne": branch["_id"]}}
        if globals.db.branches.find_one(name_query) is not None:
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
    globals.db.branches.update_one({"_id": branch["_id"]}, {"$set": updates})

    # classes keep a copy of the branch name, so update those too
    if "name" in data:
        globals.db.classes.update_many({"branch_id": branch["_id"]}, {"$set": {"branch_name": data["name"]}})

    return make_response(jsonify({"message": "Branch updated",
                                  "branch": globals.db.branches.find_one({"_id": branch["_id"]})}), 200)


# a branch can only be deleted when no members, trainers or upcoming classes use it
@branches_bp.route("/api/v1.0/branches/<string:id>", methods=["DELETE"])
@role_required("admin")
def delete_branch(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid branch ID"}), 400)
    branch = globals.db.branches.find_one({"_id": ObjectId(id)})
    if branch is None:
        return make_response(jsonify({"error": "Branch not found"}), 404)

    in_use = {
        "members": globals.db.members.count_documents({"home_branch_id": branch["_id"]}),
        "trainers": globals.db.users.count_documents({"role": "trainer", "branch_id": branch["_id"]}),
        "upcoming_classes": globals.db.classes.count_documents(
            {"branch_id": branch["_id"], "status": "scheduled", "start_time": {"$gt": now_utc()}})
    }
    linked = {}
    for name, count in in_use.items():
        if count > 0:
            linked[name] = str(count) + " linked"
    if linked:
        return make_response(jsonify({"error": "Branch is still in use and cannot be deleted",
                                      "details": linked}), 409)

    globals.db.branches.delete_one({"_id": branch["_id"]})
    return make_response(jsonify({}), 204)


# upcoming classes at one branch
@branches_bp.route("/api/v1.0/branches/<string:id>/classes", methods=["GET"])
def show_branch_classes(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid branch ID"}), 400)
    branch = globals.db.branches.find_one({"_id": ObjectId(id)})
    if branch is None:
        return make_response(jsonify({"error": "Branch not found"}), 404)

    args, errors = validate_query({
        "category": {"type": "list", "items": {"type": "string", "choices": globals.OPTIONS["workout_types"]}},
        **PAGINATION_QUERY
    })
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)

    query = {"branch_id": branch["_id"], "status": "scheduled", "start_time": {"$gt": now_utc()}}
    if "category" in args:
        query["category"] = {"$in": args["category"]}

    page_start = args["ps"] * (args["pn"] - 1)
    data = list(globals.db.classes.find(query, {"bookings": 0})
                .sort("start_time", 1).skip(page_start).limit(args["ps"]))
    for cls in data:
        cls["spaces_left"] = cls["capacity"] - cls["booked_count"]
    total = globals.db.classes.count_documents(query)
    pagination = {"page": args["pn"], "page_size": args["ps"], "total": total,
                  "pages": math.ceil(total / args["ps"])}
    return make_response(jsonify({"branch": {"_id": branch["_id"], "name": branch["name"]},
                                  "data": data, "pagination": pagination}), 200)
