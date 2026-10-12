"""
members Blueprint - member records, memberships, progress statistics and bookings.

    GET    /api/v1.0/members                    list with filters             (admin)
    POST   /api/v1.0/members                    create a member record        (admin)
    GET    /api/v1.0/members/<id>               one member                    (admin or self)
    PUT    /api/v1.0/members/<id>               update profile fields         (admin or self)
    DELETE /api/v1.0/members/<id>               delete member + account       (admin)
    PUT    /api/v1.0/members/<id>/membership    renew or change plan          (admin)
    GET    /api/v1.0/members/<id>/stats         workout statistics            (admin or self)
    GET    /api/v1.0/members/<id>/bookings      class bookings across classes (admin or self)
"""

import re
from datetime import timedelta

from flask import Blueprint, request

from decorators import ensure_self_or_admin, is_admin, jwt_required, role_required
from globals import branches, classes, exercises, members, users
from utils.constants import BOOKING_STATUSES, GENDERS, MEMBERSHIP_STATUSES, PLAN_DAYS, WORKOUT_TYPES
from utils.errors import ApiError
from utils.membership import (PROFILE_SCHEMA, REQUIRED_PROFILE_FIELDS, compute_bmi,
                              new_member_document, new_membership)
from utils.pagination import PAGINATION_QUERY, facet_envelope, facet_page
from utils.responses import created, no_content, ok
from utils.validation import now_utc, parse_object_id, to_dotted, validate_body, validate_query

members_bp = Blueprint("members", __name__)

# Admins can create members (e.g. at the front desk) without a login account
CREATE_SCHEMA = {
    "email": {"type": "email", "required": True, "max_len": 120},
    "plan": {"type": "string", "choices": list(PLAN_DAYS)},
    **{name: {**rules, "required": name in REQUIRED_PROFILE_FIELDS}
       for name, rules in PROFILE_SCHEMA.items()},
}
ADMIN_UPDATE_SCHEMA = {"email": CREATE_SCHEMA["email"], **PROFILE_SCHEMA}

# Fields left out of member lists and single-member responses (workouts have their own endpoint)
SUMMARY_PROJECTION = {"workouts": 0}


def find_member(member_id, projection=None):
    """Access check first, then lookup - shared with the workouts Blueprint.

    Checking access before existence means a member probing other ids always gets 403
    and never learns which ids exist.
    """
    oid = parse_object_id(member_id, "member id")
    ensure_self_or_admin(oid)
    member = members.find_one({"_id": oid}, projection)
    if not member:
        raise ApiError(404, "Member not found")
    return member


def _check_branch(branch_id):
    if not branches.find_one({"_id": branch_id}, {"_id": 1}):
        raise ApiError(400, "Validation failed", {"home_branch_id": "No branch exists with this id"})


def _email_taken(email, member_id=None):
    member_query = {"email": email}
    user_query = {"email": email}
    if member_id:
        member_query["_id"] = {"$ne": member_id}
        user_query["member_id"] = {"$ne": member_id}
    return members.find_one(member_query, {"_id": 1}) or users.find_one(user_query, {"_id": 1})


@members_bp.route("/members", methods=["GET"])
@role_required("admin")
def list_members():
    args = validate_query({
        "branch": {"type": "objectid"},
        "status": {"type": "string", "choices": MEMBERSHIP_STATUSES},
        "plan": {"type": "list", "items": {"type": "string", "choices": list(PLAN_DAYS)}},
        "workout_type": {"type": "list", "items": {"type": "string", "choices": WORKOUT_TYPES}},
        "gender": {"type": "string", "choices": GENDERS},
        "q": {"type": "string", "max_len": 80},
        "sort": {"type": "string", "choices": ["name", "joined_at", "age", "end_date"], "default": "name"},
        **PAGINATION_QUERY,
    })
    match = {}
    if "branch" in args:
        match["home_branch_id"] = args["branch"]
    if "status" in args:
        # Work the status out from end_date so it is always correct today,
        # even if the stored status field has not been refreshed.
        op = "$gte" if args["status"] == "active" else "$lt"
        match["membership.end_date"] = {op: now_utc()}
    if "plan" in args:
        match["membership.plan"] = {"$in": args["plan"]}
    if "workout_type" in args:
        match["preferred_workout"] = {"$in": args["workout_type"]}
    if "gender" in args:
        match["gender"] = args["gender"]
    if "q" in args:
        pattern = {"$regex": re.escape(args["q"]), "$options": "i"}
        match["$or"] = [{"name": pattern}, {"email": pattern}]

    sort_field = {"name": "name", "joined_at": "joined_at", "age": "age",
                  "end_date": "membership.end_date"}[args["sort"]]
    pipeline = [
        {"$match": match},
        {"$addFields": {"workout_count": {"$size": "$workouts"}}},
        {"$project": SUMMARY_PROJECTION},
        {"$sort": {sort_field: 1, "_id": 1}},
        facet_page(args["pn"], args["ps"]),
    ]
    return ok(facet_envelope(list(members.aggregate(pipeline)), args["pn"], args["ps"]))


@members_bp.route("/members", methods=["POST"])
@role_required("admin")
def create_member():
    data = validate_body(CREATE_SCHEMA)
    if _email_taken(data["email"]):
        raise ApiError(409, "A member with this email already exists")
    _check_branch(data["home_branch_id"])
    new_id = members.insert_one(new_member_document(data)).inserted_id
    return created("Member created", new_id, "members.get_member", id=new_id)


@members_bp.route("/members/<id>", methods=["GET"])
@jwt_required
def get_member(id):
    member = find_member(id)
    member["workout_count"] = len(member.pop("workouts"))
    branch = branches.find_one({"_id": member["home_branch_id"]}, {"name": 1})
    member["home_branch"] = branch
    return ok(member)


@members_bp.route("/members/<id>", methods=["PUT"])
@jwt_required
def update_member(id):
    member = find_member(id, SUMMARY_PROJECTION)
    if not is_admin() and "email" in (request.get_json(silent=True) or {}):
        raise ApiError(403, "Only an admin can change a member's email address")
    data = validate_body(ADMIN_UPDATE_SCHEMA if is_admin() else PROFILE_SCHEMA, partial=True)

    if "home_branch_id" in data:
        _check_branch(data["home_branch_id"])
    if "email" in data and _email_taken(data["email"], member["_id"]):
        raise ApiError(409, "Another account already uses this email")

    updates = to_dotted(data)
    if "body_metrics" in data:
        # Recalculate BMI from the new values merged with the stored ones
        metrics = {**member["body_metrics"], **data["body_metrics"]}
        updates["body_metrics.bmi"] = compute_bmi(metrics.get("weight_kg"), metrics.get("height_m"))
    members.update_one({"_id": member["_id"]}, {"$set": updates})

    # The member's name and email are copied into other collections; keep them in step.
    if "email" in data:
        users.update_one({"member_id": member["_id"]}, {"$set": {"email": data["email"]}})
    if "name" in data:
        users.update_one({"member_id": member["_id"]}, {"$set": {"name": data["name"]}})
        # array_filters update only the array elements that belong to this member
        classes.update_many({"bookings.member_id": member["_id"]},
                            {"$set": {"bookings.$[b].member_name": data["name"]}},
                            array_filters=[{"b.member_id": member["_id"]}])
        exercises.update_many({"reviews.member_id": member["_id"]},
                              {"$set": {"reviews.$[r].member_name": data["name"]}},
                              array_filters=[{"r.member_id": member["_id"]}])
    return ok({"message": "Member updated",
               "member": members.find_one({"_id": member["_id"]}, SUMMARY_PROJECTION)})


@members_bp.route("/members/<id>", methods=["DELETE"])
@role_required("admin")
def delete_member(id):
    member = find_member(id, {"_id": 1})
    mid = member["_id"]
    # Free their places in upcoming classes: mark the booking cancelled and decrement
    # booked_count in the same update so the count always matches the bookings.
    classes.update_many(
        {"status": "scheduled", "start_time": {"$gt": now_utc()},
         "bookings": {"$elemMatch": {"member_id": mid, "status": "booked"}}},
        {"$set": {"bookings.$[b].status": "cancelled"}, "$inc": {"booked_count": -1}},
        array_filters=[{"b.member_id": mid, "b.status": "booked"}],
    )
    exercises.update_many({"reviews.member_id": mid}, {"$pull": {"reviews": {"member_id": mid}}})
    users.delete_one({"member_id": mid})
    members.delete_one({"_id": mid})
    return no_content()


@members_bp.route("/members/<id>/membership", methods=["PUT"])
@role_required("admin")
def update_membership(id):
    member = find_member(id, {"membership": 1})
    data = validate_body({"plan": {"type": "string", "required": True, "choices": list(PLAN_DAYS)}})
    current = member.get("membership") or {}
    now = now_utc()

    if current.get("end_date") and current["end_date"] >= now:
        # Still active: extend from the current end date so no paid days are lost
        membership = {**current, "plan": data["plan"], "status": "active",
                      "end_date": current["end_date"] + timedelta(days=PLAN_DAYS[data["plan"]])}
        action = "renewed"
    else:
        # Expired (or never had one): a new period starts today
        membership = new_membership(data["plan"])
        action = "restarted"
    members.update_one({"_id": member["_id"]}, {"$set": {"membership": membership}})
    return ok({"message": f"Membership {action}", "membership": membership})


@members_bp.route("/members/<id>/stats", methods=["GET"])
@jwt_required
def member_stats(id):
    member = find_member(id, {"name": 1})
    args = validate_query({"weeks": {"type": "int", "min": 1, "max": 52, "default": 8}})
    since = now_utc() - timedelta(weeks=args["weeks"])

    pipeline = [
        {"$match": {"_id": member["_id"]}},
        {"$unwind": "$workouts"},                       # one document per workout
        {"$replaceRoot": {"newRoot": "$workouts"}},     # work with the workout fields directly
        {"$match": {"date": {"$gte": since}}},
        {"$facet": {                                    # several summaries in one pass
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
                              "avg_bpm": {"$round": ["$avg_bpm", 1]}}},
            ],
            "weekly": [
                # $dateTrunc rounds each date down to the Monday of its week
                {"$group": {"_id": {"$dateTrunc": {"date": "$date", "unit": "week",
                                                   "startOfWeek": "monday"}},
                            "sessions": {"$sum": 1},
                            "minutes": {"$sum": "$duration_min"},
                            "calories": {"$sum": "$calories_burned"},
                            "avg_bpm": {"$avg": "$avg_bpm"}}},
                {"$sort": {"_id": 1}},
                {"$project": {"_id": 0, "week_start": "$_id", "sessions": 1, "minutes": 1,
                              "calories": 1, "avg_bpm": {"$round": ["$avg_bpm", 1]}}},
            ],
            "by_type": [
                {"$group": {"_id": "$workout_type", "sessions": {"$sum": 1},
                            "minutes": {"$sum": "$duration_min"},
                            "calories": {"$sum": "$calories_burned"}}},
                {"$sort": {"sessions": -1, "minutes": -1}},
                {"$project": {"_id": 0, "workout_type": "$_id", "sessions": 1, "minutes": 1,
                              "calories": 1}},
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
                              "total_sets": 1, "total_reps": 1, "max_weight_kg": 1}},
            ],
        }},
    ]
    result = list(members.aggregate(pipeline))
    stats = result[0] if result else {"totals": [], "weekly": [], "by_type": [], "top_exercises": []}
    return ok({
        "member": member,
        "period": {"weeks": args["weeks"], "from": since, "to": now_utc()},
        "totals": stats["totals"][0] if stats["totals"] else {"sessions": 0},
        "favourite_workout_type": stats["by_type"][0]["workout_type"] if stats["by_type"] else None,
        "weekly": stats["weekly"],
        "by_type": stats["by_type"],
        "top_exercises": stats["top_exercises"],
    })


@members_bp.route("/members/<id>/bookings", methods=["GET"])
@jwt_required
def member_bookings(id):
    member = find_member(id, {"_id": 1})
    args = validate_query({
        "status": {"type": "string", "choices": BOOKING_STATUSES},
        "when": {"type": "string", "choices": ["upcoming", "past", "all"], "default": "all"},
        **PAGINATION_QUERY,
    })
    mid = member["_id"]
    class_match = {"bookings.member_id": mid}          # uses the bookings.member_id index
    if args["when"] == "upcoming":
        class_match["start_time"] = {"$gt": now_utc()}
    elif args["when"] == "past":
        class_match["start_time"] = {"$lte": now_utc()}
    booking_match = {"bookings.member_id": mid}
    if "status" in args:
        booking_match["bookings.status"] = args["status"]

    pipeline = [
        {"$match": class_match},
        {"$unwind": "$bookings"},
        {"$match": booking_match},                     # keep only this member's bookings
        {"$sort": {"start_time": 1 if args["when"] == "upcoming" else -1}},
        {"$project": {
            "_id": "$bookings._id",
            "status": "$bookings.status",
            "booked_at": "$bookings.booked_at",
            "attended": "$bookings.attended",
            "class": {"_id": "$_id", "title": "$title", "category": "$category",
                      "branch_id": "$branch_id", "branch_name": "$branch_name",
                      "trainer_name": "$trainer_name", "start_time": "$start_time",
                      "duration_min": "$duration_min", "status": "$status"},
        }},
        facet_page(args["pn"], args["ps"]),
    ]
    return ok(facet_envelope(list(classes.aggregate(pipeline)), args["pn"], args["ps"]))
