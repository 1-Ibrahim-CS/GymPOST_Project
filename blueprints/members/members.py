import math
import re
from datetime import timedelta

from bson import ObjectId
from flask import Blueprint, g, jsonify, make_response, request

from decorators import jwt_required, role_required
from globals import branches, classes, exercises, members, users
from utils.constants import (BOOKING_STATUSES, GENDERS, MEMBERSHIP_STATUSES, PAGINATION_QUERY,
                             PLAN_DAYS, WORKOUT_TYPES)
from utils.membership import (PROFILE_SCHEMA, REQUIRED_PROFILE_FIELDS, compute_bmi,
                              new_member_document, new_membership)
from utils.validation import now_utc, to_dotted, validate_body, validate_query

members_bp = Blueprint("members", __name__)

# admins can add a member at the front desk without a login account
CREATE_SCHEMA = {
    "email": {"type": "email", "required": True, "max_len": 120},
    "plan": {"type": "string", "choices": list(PLAN_DAYS)},
}
for field_name, field_rules in PROFILE_SCHEMA.items():
    CREATE_SCHEMA[field_name] = {**field_rules, "required": field_name in REQUIRED_PROFILE_FIELDS}

# admins can also change the email, members can't
ADMIN_UPDATE_SCHEMA = {"email": CREATE_SCHEMA["email"], **PROFILE_SCHEMA}


# True if another member or user account already uses this email
def email_taken(email, member_id=None):
    member_query = {"email": email}
    user_query = {"email": email}
    if member_id:
        member_query["_id"] = {"$ne": member_id}
        user_query["member_id"] = {"$ne": member_id}
    return members.find_one(member_query) is not None or users.find_one(user_query) is not None


@members_bp.route("/api/v1.0/members", methods=["GET"])
@role_required("admin")
def show_all_members():
    args, errors = validate_query({
        "branch": {"type": "objectid"},
        "status": {"type": "string", "choices": MEMBERSHIP_STATUSES},
        "plan": {"type": "list", "items": {"type": "string", "choices": list(PLAN_DAYS)}},
        "workout_type": {"type": "list", "items": {"type": "string", "choices": WORKOUT_TYPES}},
        "gender": {"type": "string", "choices": GENDERS},
        "q": {"type": "string", "max_len": 80},
        "sort": {"type": "string", "choices": ["name", "joined_at", "age", "end_date"], "default": "name"},
        **PAGINATION_QUERY
    })
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)

    match = {}
    if "branch" in args:
        match["home_branch_id"] = args["branch"]
    if "status" in args:
        # worked out from end_date so it is always right today
        if args["status"] == "active":
            match["membership.end_date"] = {"$gte": now_utc()}
        else:
            match["membership.end_date"] = {"$lt": now_utc()}
    if "plan" in args:
        match["membership.plan"] = {"$in": args["plan"]}
    if "workout_type" in args:
        match["preferred_workout"] = {"$in": args["workout_type"]}
    if "gender" in args:
        match["gender"] = args["gender"]
    if "q" in args:
        pattern = {"$regex": re.escape(args["q"]), "$options": "i"}
        match["$or"] = [{"name": pattern}, {"email": pattern}]

    sort_field = args["sort"]
    if sort_field == "end_date":
        sort_field = "membership.end_date"

    page_start = args["ps"] * (args["pn"] - 1)
    pipeline = [
        {"$match": match},
        {"$addFields": {"workout_count": {"$size": "$workouts"}}},
        {"$project": {"workouts": 0}},
        {"$sort": {sort_field: 1, "_id": 1}},
        {"$facet": {"data": [{"$skip": page_start}, {"$limit": args["ps"]}],
                    "total": [{"$count": "count"}]}}
    ]
    result = list(members.aggregate(pipeline))[0]
    total = result["total"][0]["count"] if result["total"] else 0
    pagination = {"page": args["pn"], "page_size": args["ps"], "total": total,
                  "pages": math.ceil(total / args["ps"])}
    return make_response(jsonify({"data": result["data"], "pagination": pagination}), 200)


@members_bp.route("/api/v1.0/members", methods=["POST"])
@role_required("admin")
def add_new_member():
    data, errors = validate_body(CREATE_SCHEMA)
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)
    if email_taken(data["email"]):
        return make_response(jsonify({"error": "A member with this email already exists"}), 409)
    if branches.find_one({"_id": data["home_branch_id"]}) is None:
        return make_response(jsonify({"error": "Validation failed",
                                      "details": {"home_branch_id": "No branch exists with this id"}}), 400)

    new_id = members.insert_one(new_member_document(data)).inserted_id
    new_member_link = request.host_url + "api/v1.0/members/" + str(new_id)
    response = make_response(jsonify({"message": "Member created", "id": str(new_id), "url": new_member_link}), 201)
    response.headers["Location"] = new_member_link
    return response


# admin or the member themself
@members_bp.route("/api/v1.0/members/<string:id>", methods=["GET"])
@jwt_required
def show_one_member(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid member ID"}), 400)
    # access is checked before the lookup so members can't find out which ids exist
    if g.user["role"] != "admin" and g.user["member_id"] != str(ObjectId(id)):
        return make_response(jsonify({"error": "You can only access your own member record"}), 403)
    member = members.find_one({"_id": ObjectId(id)})
    if member is None:
        return make_response(jsonify({"error": "Member not found"}), 404)

    member["workout_count"] = len(member.pop("workouts"))
    member["home_branch"] = branches.find_one({"_id": member["home_branch_id"]}, {"name": 1})
    return make_response(jsonify(member), 200)


# admin or the member themself - only an admin can change the email
@members_bp.route("/api/v1.0/members/<string:id>", methods=["PUT"])
@jwt_required
def edit_member(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid member ID"}), 400)
    is_admin = g.user["role"] == "admin"
    if not is_admin and g.user["member_id"] != str(ObjectId(id)):
        return make_response(jsonify({"error": "You can only access your own member record"}), 403)
    member = members.find_one({"_id": ObjectId(id)}, {"workouts": 0})
    if member is None:
        return make_response(jsonify({"error": "Member not found"}), 404)

    if not is_admin and "email" in (request.get_json(silent=True) or {}):
        return make_response(jsonify({"error": "Only an admin can change a member's email address"}), 403)
    if is_admin:
        data, errors = validate_body(ADMIN_UPDATE_SCHEMA, partial=True)
    else:
        data, errors = validate_body(PROFILE_SCHEMA, partial=True)
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)

    if "home_branch_id" in data and branches.find_one({"_id": data["home_branch_id"]}) is None:
        return make_response(jsonify({"error": "Validation failed",
                                      "details": {"home_branch_id": "No branch exists with this id"}}), 400)
    if "email" in data and email_taken(data["email"], member["_id"]):
        return make_response(jsonify({"error": "Another account already uses this email"}), 409)

    updates = to_dotted(data)
    if "body_metrics" in data:
        # recalculate BMI from the new values and the stored ones
        metrics = {**member["body_metrics"], **data["body_metrics"]}
        updates["body_metrics.bmi"] = compute_bmi(metrics.get("weight_kg"), metrics.get("height_m"))
    members.update_one({"_id": member["_id"]}, {"$set": updates})

    # the name and email are copied into other collections, so update those too
    if "email" in data:
        users.update_one({"member_id": member["_id"]}, {"$set": {"email": data["email"]}})
    if "name" in data:
        users.update_one({"member_id": member["_id"]}, {"$set": {"name": data["name"]}})
        # array_filters only change the bookings / reviews that belong to this member
        classes.update_many({"bookings.member_id": member["_id"]},
                            {"$set": {"bookings.$[b].member_name": data["name"]}},
                            array_filters=[{"b.member_id": member["_id"]}])
        exercises.update_many({"reviews.member_id": member["_id"]},
                              {"$set": {"reviews.$[r].member_name": data["name"]}},
                              array_filters=[{"r.member_id": member["_id"]}])

    return make_response(jsonify({"message": "Member updated",
                                  "member": members.find_one({"_id": member["_id"]}, {"workouts": 0})}), 200)


@members_bp.route("/api/v1.0/members/<string:id>", methods=["DELETE"])
@role_required("admin")
def delete_member(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid member ID"}), 400)
    member = members.find_one({"_id": ObjectId(id)}, {"_id": 1})
    if member is None:
        return make_response(jsonify({"error": "Member not found"}), 404)
    member_id = member["_id"]

    # free their places in upcoming classes - cancel the booking and lower
    # booked_count in the same update so the count always matches the bookings
    classes.update_many(
        {"status": "scheduled", "start_time": {"$gt": now_utc()},
         "bookings": {"$elemMatch": {"member_id": member_id, "status": "booked"}}},
        {"$set": {"bookings.$[b].status": "cancelled"}, "$inc": {"booked_count": -1}},
        array_filters=[{"b.member_id": member_id, "b.status": "booked"}]
    )
    exercises.update_many({"reviews.member_id": member_id}, {"$pull": {"reviews": {"member_id": member_id}}})
    users.delete_one({"member_id": member_id})
    members.delete_one({"_id": member_id})
    return make_response(jsonify({}), 204)


# renew or change the membership plan
@members_bp.route("/api/v1.0/members/<string:id>/membership", methods=["PUT"])
@role_required("admin")
def edit_membership(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid member ID"}), 400)
    member = members.find_one({"_id": ObjectId(id)}, {"membership": 1})
    if member is None:
        return make_response(jsonify({"error": "Member not found"}), 404)

    data, errors = validate_body({"plan": {"type": "string", "required": True, "choices": list(PLAN_DAYS)}})
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)

    current = member.get("membership") or {}
    if current.get("end_date") and current["end_date"] >= now_utc():
        # still active - add the new period on to the current end date
        membership = {**current, "plan": data["plan"], "status": "active",
                      "end_date": current["end_date"] + timedelta(days=PLAN_DAYS[data["plan"]])}
        message = "Membership renewed"
    else:
        # expired - a new period starts today
        membership = new_membership(data["plan"])
        message = "Membership restarted"
    members.update_one({"_id": member["_id"]}, {"$set": {"membership": membership}})
    return make_response(jsonify({"message": message, "membership": membership}), 200)


# workout statistics for the last few weeks
@members_bp.route("/api/v1.0/members/<string:id>/stats", methods=["GET"])
@jwt_required
def show_member_stats(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid member ID"}), 400)
    if g.user["role"] != "admin" and g.user["member_id"] != str(ObjectId(id)):
        return make_response(jsonify({"error": "You can only access your own member record"}), 403)
    member = members.find_one({"_id": ObjectId(id)}, {"name": 1})
    if member is None:
        return make_response(jsonify({"error": "Member not found"}), 404)

    args, errors = validate_query({"weeks": {"type": "int", "min": 1, "max": 52, "default": 8}})
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)
    since = now_utc() - timedelta(weeks=args["weeks"])

    pipeline = [
        {"$match": {"_id": member["_id"]}},
        {"$unwind": "$workouts"},                       # one document per workout
        {"$replaceRoot": {"newRoot": "$workouts"}},
        {"$match": {"date": {"$gte": since}}},
        {"$facet": {
            "totals": [
                {"$group": {"_id": None,
                            "sessions": {"$sum": 1},
                            "total_minutes": {"$sum": "$duration_min"},
                            "total_calories": {"$sum": "$calories_burned"},
                            "avg_duration_min": {"$avg": "$duration_min"},
                            "avg_calories": {"$avg": "$calories_burned"},
                            "avg_bpm": {"$avg": "$avg_bpm"},
                            "peak_bpm": {"$max": "$max_bpm"},
                            "first_workout": {"$min": "$date"},
                            "last_workout": {"$max": "$date"}}},
                {"$project": {"_id": 0, "sessions": 1, "total_minutes": 1, "total_calories": 1,
                              "peak_bpm": 1, "first_workout": 1, "last_workout": 1,
                              "avg_duration_min": {"$round": ["$avg_duration_min", 1]},
                              "avg_calories": {"$round": ["$avg_calories", 1]},
                              "avg_bpm": {"$round": ["$avg_bpm", 1]}}}
            ],
            "weekly": [
                # $dateTrunc rounds each date down to the Monday of its week
                {"$group": {"_id": {"$dateTrunc": {"date": "$date", "unit": "week", "startOfWeek": "monday"}},
                            "sessions": {"$sum": 1},
                            "minutes": {"$sum": "$duration_min"},
                            "calories": {"$sum": "$calories_burned"},
                            "avg_bpm": {"$avg": "$avg_bpm"}}},
                {"$sort": {"_id": 1}},
                {"$project": {"_id": 0, "week_start": "$_id", "sessions": 1, "minutes": 1,
                              "calories": 1, "avg_bpm": {"$round": ["$avg_bpm", 1]}}}
            ],
            "by_type": [
                {"$group": {"_id": "$workout_type", "sessions": {"$sum": 1},
                            "minutes": {"$sum": "$duration_min"},
                            "calories": {"$sum": "$calories_burned"}}},
                {"$sort": {"sessions": -1, "minutes": -1}},
                {"$project": {"_id": 0, "workout_type": "$_id", "sessions": 1, "minutes": 1, "calories": 1}}
            ],
            "top_exercises": [
                {"$unwind": "$exercises"},
                {"$group": {"_id": "$exercises.exercise_id",
                            "title": {"$first": "$exercises.title"},
                            "times_done": {"$sum": 1},
                            "total_sets": {"$sum": "$exercises.sets"},
                            "total_reps": {"$sum": {"$multiply": ["$exercises.sets", "$exercises.reps"]}},
                            "max_weight_kg": {"$max": "$exercises.weight_kg"}}},
                {"$sort": {"times_done": -1, "total_sets": -1}},
                {"$limit": 5},
                {"$project": {"_id": 0, "exercise_id": "$_id", "title": 1, "times_done": 1,
                              "total_sets": 1, "total_reps": 1, "max_weight_kg": 1}}
            ]
        }}
    ]
    stats = list(members.aggregate(pipeline))[0]
    return make_response(jsonify({
        "member": member,
        "period": {"weeks": args["weeks"], "from": since, "to": now_utc()},
        "totals": stats["totals"][0] if stats["totals"] else {"sessions": 0},
        "favourite_workout_type": stats["by_type"][0]["workout_type"] if stats["by_type"] else None,
        "weekly": stats["weekly"],
        "by_type": stats["by_type"],
        "top_exercises": stats["top_exercises"]
    }), 200)


# the member's bookings across all classes
@members_bp.route("/api/v1.0/members/<string:id>/bookings", methods=["GET"])
@jwt_required
def show_member_bookings(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid member ID"}), 400)
    if g.user["role"] != "admin" and g.user["member_id"] != str(ObjectId(id)):
        return make_response(jsonify({"error": "You can only access your own member record"}), 403)
    member = members.find_one({"_id": ObjectId(id)}, {"_id": 1})
    if member is None:
        return make_response(jsonify({"error": "Member not found"}), 404)

    args, errors = validate_query({
        "status": {"type": "string", "choices": BOOKING_STATUSES},
        "when": {"type": "string", "choices": ["upcoming", "past", "all"], "default": "all"},
        **PAGINATION_QUERY
    })
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)

    class_match = {"bookings.member_id": member["_id"]}
    if args["when"] == "upcoming":
        class_match["start_time"] = {"$gt": now_utc()}
    elif args["when"] == "past":
        class_match["start_time"] = {"$lte": now_utc()}
    booking_match = {"bookings.member_id": member["_id"]}
    if "status" in args:
        booking_match["bookings.status"] = args["status"]

    page_start = args["ps"] * (args["pn"] - 1)
    pipeline = [
        {"$match": class_match},
        {"$unwind": "$bookings"},
        {"$match": booking_match},                     # only this member's bookings
        {"$sort": {"start_time": 1 if args["when"] == "upcoming" else -1}},
        {"$project": {
            "_id": "$bookings._id",
            "status": "$bookings.status",
            "booked_at": "$bookings.booked_at",
            "attended": "$bookings.attended",
            "class": {"_id": "$_id", "title": "$title", "category": "$category",
                      "branch_id": "$branch_id", "branch_name": "$branch_name",
                      "trainer_name": "$trainer_name", "start_time": "$start_time",
                      "duration_min": "$duration_min", "status": "$status"}
        }},
        {"$facet": {"data": [{"$skip": page_start}, {"$limit": args["ps"]}],
                    "total": [{"$count": "count"}]}}
    ]
    result = list(classes.aggregate(pipeline))[0]
    total = result["total"][0]["count"] if result["total"] else 0
    pagination = {"page": args["pn"], "page_size": args["ps"], "total": total,
                  "pages": math.ceil(total / args["ps"])}
    return make_response(jsonify({"data": result["data"], "pagination": pagination}), 200)
