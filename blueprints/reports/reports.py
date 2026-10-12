from datetime import timedelta

from flask import Blueprint, jsonify, make_response

from decorators import role_required
from globals import branches, classes, members
from utils.constants import WORKOUT_TYPES
from utils.validation import now_utc, validate_query

reports_bp = Blueprint("reports", __name__)

# admin reports built with aggregation pipelines
#   fill rate       = booked places / capacity
#   attendance rate = bookings marked attended / bookings, only for classes that have already happened

DATE_RANGE_QUERY = {"from": {"type": "datetime"}, "to": {"type": "datetime"},
                    "branch": {"type": "objectid"}}

# number of bookings in a class marked attended
ATTENDED_COUNT = {"$size": {"$filter": {"input": "$bookings",
                                        "cond": {"$eq": ["$$this.attended", True]}}}}


# numerator / denominator as a percentage to 1 decimal place, or null when dividing by 0
def percent(numerator, denominator):
    return {"$cond": [{"$gt": [denominator, 0]},
                      {"$round": [{"$multiply": [{"$divide": [numerator, denominator]}, 100]}, 1]},
                      None]}


# classes that were not cancelled, inside the optional date range and branch
def class_match(args):
    match = {"status": {"$ne": "cancelled"}}
    if "from" in args or "to" in args:
        match["start_time"] = {}
        if "from" in args:
            match["start_time"]["$gte"] = args["from"]
        if "to" in args:
            match["start_time"]["$lte"] = args["to"]
    if "branch" in args:
        match["branch_id"] = args["branch"]
    return match


# $project stage used by the class reports
def class_fields(now):
    happened = {"$lte": ["$start_time", now]}
    return {"$project": {
        "title": 1, "category": 1, "trainer_id": 1, "trainer_name": 1, "branch_id": 1,
        "start_time": 1, "capacity": 1, "booked_count": 1,
        "happened": happened,
        "attended": ATTENDED_COUNT,
        # only classes that have happened count towards attendance
        "past_booked": {"$cond": [happened, "$booked_count", 0]}
    }}


# group stage + rates, used for the per-class and per-category results
def class_summary(group_id):
    return [
        {"$group": {"_id": group_id,
                    "classes": {"$sum": 1},
                    "bookings": {"$sum": "$booked_count"},
                    "capacity": {"$sum": "$capacity"},
                    "attended": {"$sum": "$attended"},
                    "past_booked": {"$sum": "$past_booked"}}},
        {"$addFields": {"fill_rate": percent("$bookings", "$capacity"),
                        "attendance_rate": percent("$attended", "$past_booked")}}
    ]


# bookings, fill rate and attendance by class and by category
@reports_bp.route("/api/v1.0/reports/popular-classes", methods=["GET"])
@role_required("admin")
def show_popular_classes():
    args, errors = validate_query({
        **DATE_RANGE_QUERY,
        "category": {"type": "list", "items": {"type": "string", "choices": WORKOUT_TYPES}},
        "sort": {"type": "string", "choices": ["bookings", "fill_rate", "attendance_rate"], "default": "bookings"},
        "limit": {"type": "int", "min": 1, "max": 50, "default": 10}
    })
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)
    if "from" in args and "to" in args and args["from"] > args["to"]:
        return make_response(jsonify({"error": "Invalid query parameters",
                                      "details": {"from": "Must be before 'to'"}}), 400)

    match = class_match(args)
    if "category" in args:
        match["category"] = {"$in": args["category"]}

    pipeline = [
        {"$match": match},
        class_fields(now_utc()),
        {"$facet": {
            "by_class": class_summary({"category": "$category", "title": "$title"}) + [
                {"$sort": {args["sort"]: -1, "bookings": -1}},
                {"$limit": args["limit"]},
                {"$project": {"_id": 0, "category": "$_id.category", "title": "$_id.title",
                              "classes": 1, "bookings": 1, "capacity": 1, "fill_rate": 1,
                              "attended": 1, "attendance_rate": 1}}
            ],
            "by_category": class_summary("$category") + [
                {"$sort": {"bookings": -1}},
                {"$project": {"_id": 0, "category": "$_id", "classes": 1, "bookings": 1,
                              "fill_rate": 1, "attendance_rate": 1}}
            ]
        }}
    ]
    result = list(classes.aggregate(pipeline))[0]
    return make_response(jsonify({"sorted_by": args["sort"], "by_class": result["by_class"],
                                  "by_category": result["by_category"]}), 200)


# members, bookings and fill rate for each branch
@reports_bp.route("/api/v1.0/reports/branch-usage", methods=["GET"])
@role_required("admin")
def show_branch_usage():
    args, errors = validate_query({"from": {"type": "datetime"}, "to": {"type": "datetime"}})
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)
    if "from" in args and "to" in args and args["from"] > args["to"]:
        return make_response(jsonify({"error": "Invalid query parameters",
                                      "details": {"from": "Must be before 'to'"}}), 400)
    now = now_utc()

    pipeline = [
        # $lookup with a pipeline counts the branch's members without copying them all in
        {"$lookup": {
            "from": "members",
            "let": {"branch_id": "$_id"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$home_branch_id", "$$branch_id"]}}},
                {"$group": {"_id": None,
                            "total": {"$sum": 1},
                            "active": {"$sum": {"$cond": [{"$gte": ["$membership.end_date", now]}, 1, 0]}}}}
            ],
            "as": "member_stats"
        }},
        {"$lookup": {
            "from": "classes",
            "let": {"branch_id": "$_id"},
            "pipeline": [
                {"$match": {**class_match(args), "$expr": {"$eq": ["$branch_id", "$$branch_id"]}}},
                class_fields(now),
                {"$group": {"_id": None,
                            "classes": {"$sum": 1},
                            "bookings": {"$sum": "$booked_count"},
                            "capacity": {"$sum": "$capacity"},
                            "attended": {"$sum": "$attended"},
                            "past_booked": {"$sum": "$past_booked"}}}
            ],
            "as": "class_stats"
        }},
        # each lookup gives a one-element array (or an empty one) - take the first element
        {"$set": {"m": {"$ifNull": [{"$first": "$member_stats"}, {}]},
                  "c": {"$ifNull": [{"$first": "$class_stats"}, {}]}}},
        {"$project": {
            "_id": 0, "branch_id": "$_id", "name": 1, "city": "$address.city",
            "members": {"$ifNull": ["$m.total", 0]},
            "active_members": {"$ifNull": ["$m.active", 0]},
            "classes": {"$ifNull": ["$c.classes", 0]},
            "bookings": {"$ifNull": ["$c.bookings", 0]},
            "fill_rate": percent({"$ifNull": ["$c.bookings", 0]}, {"$ifNull": ["$c.capacity", 0]}),
            "attendance_rate": percent({"$ifNull": ["$c.attended", 0]}, {"$ifNull": ["$c.past_booked", 0]}),
            "bookings_per_active_member": {"$cond": [
                {"$gt": ["$m.active", 0]},
                {"$round": [{"$divide": ["$c.bookings", "$m.active"]}, 2]}, None]}
        }},
        {"$sort": {"bookings": -1}}
    ]
    data = list(branches.aggregate(pipeline))
    return make_response(jsonify({"data": data, "count": len(data)}), 200)


# bookings by weekday and hour
@reports_bp.route("/api/v1.0/reports/peak-times", methods=["GET"])
@role_required("admin")
def show_peak_times():
    args, errors = validate_query({**DATE_RANGE_QUERY,
                                   "limit": {"type": "int", "min": 1, "max": 50, "default": 10}})
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)
    if "from" in args and "to" in args and args["from"] > args["to"]:
        return make_response(jsonify({"error": "Invalid query parameters",
                                      "details": {"from": "Must be before 'to'"}}), 400)
    day_names = ["", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

    pipeline = [
        {"$match": class_match(args)},
        {"$unwind": "$bookings"},                          # one document per booking
        {"$match": {"bookings.status": "booked"}},
        {"$project": {"class_id": "$_id",
                      "day": {"$dayOfWeek": "$start_time"},     # 1 = Sunday ... 7 = Saturday
                      "hour": {"$hour": "$start_time"}}},
        {"$facet": {
            "busiest_slots": [
                {"$group": {"_id": {"day": "$day", "hour": "$hour"},
                            "bookings": {"$sum": 1}, "classes": {"$addToSet": "$class_id"}}},
                {"$project": {"_id": 0, "day_number": "$_id.day", "hour": "$_id.hour", "bookings": 1,
                              "day": {"$arrayElemAt": [day_names, "$_id.day"]},
                              "classes": {"$size": "$classes"},
                              "avg_bookings_per_class": {"$round": [
                                  {"$divide": ["$bookings", {"$size": "$classes"}]}, 1]}}},
                {"$sort": {"bookings": -1}},
                {"$limit": args["limit"]}
            ],
            "by_weekday": [
                {"$group": {"_id": "$day", "bookings": {"$sum": 1}}},
                {"$sort": {"_id": 1}},
                {"$project": {"_id": 0, "day_number": "$_id", "bookings": 1,
                              "day": {"$arrayElemAt": [day_names, "$_id"]}}}
            ],
            "by_hour": [
                {"$group": {"_id": "$hour", "bookings": {"$sum": 1}}},
                {"$sort": {"_id": 1}},
                {"$project": {"_id": 0, "hour": "$_id", "bookings": 1}}
            ]
        }}
    ]
    result = list(classes.aggregate(pipeline))[0]
    return make_response(jsonify({"timezone": "UTC", "busiest_slots": result["busiest_slots"],
                                  "by_weekday": result["by_weekday"], "by_hour": result["by_hour"]}), 200)


# classes taught, fill rate and attendance for each trainer
@reports_bp.route("/api/v1.0/reports/trainer-performance", methods=["GET"])
@role_required("admin")
def show_trainer_performance():
    args, errors = validate_query({
        **DATE_RANGE_QUERY,
        "sort": {"type": "string", "choices": ["attendance_rate", "fill_rate", "classes_taught"],
                 "default": "attendance_rate"}
    })
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)
    if "from" in args and "to" in args and args["from"] > args["to"]:
        return make_response(jsonify({"error": "Invalid query parameters",
                                      "details": {"from": "Must be before 'to'"}}), 400)

    pipeline = [
        {"$match": class_match(args)},
        class_fields(now_utc()),
        {"$group": {"_id": "$trainer_id",
                    "trainer_name": {"$first": "$trainer_name"},
                    "classes_taught": {"$sum": {"$cond": ["$happened", 1, 0]}},
                    "upcoming_classes": {"$sum": {"$cond": ["$happened", 0, 1]}},
                    "bookings": {"$sum": "$booked_count"},
                    "capacity": {"$sum": "$capacity"},
                    "attended": {"$sum": "$attended"},
                    "past_booked": {"$sum": "$past_booked"},
                    "categories": {"$addToSet": "$category"}}},
        # join the trainer's account for their specialities and home branch
        {"$lookup": {"from": "users", "localField": "_id", "foreignField": "_id",
                     "as": "trainer", "pipeline": [{"$project": {"specialities": 1, "branch_id": 1}}]}},
        {"$lookup": {"from": "branches", "localField": "trainer.branch_id", "foreignField": "_id",
                     "as": "branch", "pipeline": [{"$project": {"name": 1}}]}},
        {"$project": {
            "_id": 0, "trainer_id": "$_id", "trainer_name": 1,
            "branch": {"$first": "$branch.name"},
            "specialities": {"$first": "$trainer.specialities"},
            "categories": 1, "classes_taught": 1, "upcoming_classes": 1, "bookings": 1,
            "fill_rate": percent("$bookings", "$capacity"),
            "attendance_rate": percent("$attended", "$past_booked")
        }},
        {"$sort": {args["sort"]: -1, "trainer_name": 1}}
    ]
    data = list(classes.aggregate(pipeline))
    return make_response(jsonify({"sorted_by": args["sort"], "data": data, "count": len(data)}), 200)


# plans, statuses and memberships ending soon
@reports_bp.route("/api/v1.0/reports/membership-summary", methods=["GET"])
@role_required("admin")
def show_membership_summary():
    args, errors = validate_query({"days": {"type": "int", "min": 1, "max": 365, "default": 30},
                                   "limit": {"type": "int", "min": 1, "max": 100, "default": 20},
                                   "branch": {"type": "objectid"}})
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)

    now = now_utc()
    horizon = now + timedelta(days=args["days"])
    match = {}
    if "branch" in args:
        match["home_branch_id"] = args["branch"]
    expiring = {"membership.end_date": {"$gte": now, "$lte": horizon}}

    # status is worked out from end_date so it's right even if the stored status is old
    status_expr = {"$cond": [{"$gte": ["$membership.end_date", now]}, "active", "expired"]}
    pipeline = [
        {"$match": match},
        {"$facet": {
            "total": [{"$count": "members"}],
            "by_status": [
                {"$group": {"_id": status_expr, "members": {"$sum": 1}}},
                {"$project": {"_id": 0, "status": "$_id", "members": 1}},
                {"$sort": {"status": 1}}
            ],
            "by_plan": [
                {"$group": {"_id": "$membership.plan",
                            "members": {"$sum": 1},
                            "active": {"$sum": {"$cond": [{"$eq": [status_expr, "active"]}, 1, 0]}}}},
                {"$project": {"_id": 0, "plan": "$_id", "members": 1, "active": 1,
                              "expired": {"$subtract": ["$members", "$active"]}}},
                {"$sort": {"members": -1}}
            ],
            "expiring_count": [{"$match": expiring}, {"$count": "members"}],
            "expiring_soon": [
                {"$match": expiring},
                {"$sort": {"membership.end_date": 1}},
                {"$limit": args["limit"]},
                {"$project": {"name": 1, "email": 1, "home_branch_id": 1,
                              "plan": "$membership.plan", "end_date": "$membership.end_date",
                              "days_left": {"$dateDiff": {"startDate": now,
                                                          "endDate": "$membership.end_date",
                                                          "unit": "day"}}}}
            ]
        }}
    ]
    result = list(members.aggregate(pipeline))[0]
    return make_response(jsonify({
        "total_members": result["total"][0]["members"] if result["total"] else 0,
        "by_status": result["by_status"],
        "by_plan": result["by_plan"],
        "expiring_soon": {
            "within_days": args["days"],
            "count": result["expiring_count"][0]["members"] if result["expiring_count"] else 0,
            "members": result["expiring_soon"]           # soonest first
        }
    }), 200)
