"""
reports Blueprint - management reports built with aggregation pipelines (admin only).

    GET /api/v1.0/reports/popular-classes        bookings, fill rate, attendance by class
    GET /api/v1.0/reports/branch-usage           members, bookings and fill rate per branch
    GET /api/v1.0/reports/peak-times             bookings by weekday and hour
    GET /api/v1.0/reports/trainer-performance    classes taught, fill and attendance per trainer
    GET /api/v1.0/reports/membership-summary     plans, statuses and memberships expiring soon

Definitions used throughout:
    fill rate        = booked places / capacity
    attendance rate  = bookings marked attended / active bookings, for classes that have
                       already happened (start_time in the past)
"""

from datetime import timedelta

from flask import Blueprint

from decorators import role_required
from globals import branches, classes, members
from utils.constants import WORKOUT_TYPES
from utils.errors import ApiError
from utils.responses import ok
from utils.validation import now_utc, validate_query

reports_bp = Blueprint("reports", __name__)

DATE_RANGE_QUERY = {"from": {"type": "datetime"}, "to": {"type": "datetime"},
                    "branch": {"type": "objectid"}}

# Expression: number of bookings in the class's bookings array marked attended
ATTENDED_COUNT = {"$size": {"$filter": {"input": "$bookings",
                                        "cond": {"$eq": ["$$this.attended", True]}}}}


def _percent(numerator, denominator):
    """Expression: numerator / denominator as a percentage (1 d.p.), or null if dividing by 0."""
    return {"$cond": [{"$gt": [denominator, 0]},
                      {"$round": [{"$multiply": [{"$divide": [numerator, denominator]}, 100]}, 1]},
                      None]}


def _class_match(args):
    """$match for classes that were not cancelled, within the optional date range / branch."""
    if "from" in args and "to" in args and args["from"] > args["to"]:
        raise ApiError(400, "Invalid query parameters", {"from": "Must be before 'to'"})
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


def _class_fields(now):
    """$project stage shared by the class-based reports."""
    happened = {"$lte": ["$start_time", now]}
    return {"$project": {
        "title": 1, "category": 1, "trainer_id": 1, "trainer_name": 1, "branch_id": 1,
        "start_time": 1, "capacity": 1, "booked_count": 1,
        "happened": happened,
        "attended": ATTENDED_COUNT,
        # only bookings for classes that have happened count towards attendance
        "past_booked": {"$cond": [happened, "$booked_count", 0]},
    }}


@reports_bp.route("/reports/popular-classes", methods=["GET"])
@role_required("admin")
def popular_classes():
    args = validate_query({
        **DATE_RANGE_QUERY,
        "category": {"type": "list", "items": {"type": "string", "choices": WORKOUT_TYPES}},
        "sort": {"type": "string", "choices": ["bookings", "fill_rate", "attendance_rate"],
                 "default": "bookings"},
        "limit": {"type": "int", "min": 1, "max": 50, "default": 10},
    })
    match = _class_match(args)
    if "category" in args:
        match["category"] = {"$in": args["category"]}

    def summary(group_id):
        """Group stage + rate calculation, reused for per-class and per-category results."""
        return [
            {"$group": {"_id": group_id,
                        "classes": {"$sum": 1},
                        "bookings": {"$sum": "$booked_count"},
                        "capacity": {"$sum": "$capacity"},
                        "attended": {"$sum": "$attended"},
                        "past_booked": {"$sum": "$past_booked"}}},
            {"$addFields": {"fill_rate": _percent("$bookings", "$capacity"),
                            "attendance_rate": _percent("$attended", "$past_booked")}},
        ]

    pipeline = [
        {"$match": match},
        _class_fields(now_utc()),
        {"$facet": {
            "by_class": summary({"category": "$category", "title": "$title"}) + [
                {"$sort": {args["sort"]: -1, "bookings": -1}},
                {"$limit": args["limit"]},
                {"$project": {"_id": 0, "category": "$_id.category", "title": "$_id.title",
                              "classes": 1, "bookings": 1, "capacity": 1, "fill_rate": 1,
                              "attended": 1, "attendance_rate": 1}},
            ],
            "by_category": summary("$category") + [
                {"$sort": {"bookings": -1}},
                {"$project": {"_id": 0, "category": "$_id", "classes": 1, "bookings": 1,
                              "fill_rate": 1, "attendance_rate": 1}},
            ],
        }},
    ]
    result = list(classes.aggregate(pipeline))[0]
    return ok({"sorted_by": args["sort"], **result})


@reports_bp.route("/reports/branch-usage", methods=["GET"])
@role_required("admin")
def branch_usage():
    args = validate_query({"from": DATE_RANGE_QUERY["from"], "to": DATE_RANGE_QUERY["to"]})
    class_match = _class_match(args)
    now = now_utc()

    pipeline = [
        # $lookup with a sub-pipeline: count this branch's members without
        # copying every member document into the result
        {"$lookup": {
            "from": "members",
            "let": {"branch_id": "$_id"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$home_branch_id", "$$branch_id"]}}},
                {"$group": {"_id": None,
                            "total": {"$sum": 1},
                            "active": {"$sum": {"$cond": [{"$gte": ["$membership.end_date", now]}, 1, 0]}}}},
            ],
            "as": "member_stats",
        }},
        {"$lookup": {
            "from": "classes",
            "let": {"branch_id": "$_id"},
            "pipeline": [
                {"$match": {**class_match, "$expr": {"$eq": ["$branch_id", "$$branch_id"]}}},
                _class_fields(now),
                {"$group": {"_id": None,
                            "classes": {"$sum": 1},
                            "bookings": {"$sum": "$booked_count"},
                            "capacity": {"$sum": "$capacity"},
                            "attended": {"$sum": "$attended"},
                            "past_booked": {"$sum": "$past_booked"}}},
            ],
            "as": "class_stats",
        }},
        # Each lookup returns a one-element array (or empty): take the first element
        {"$set": {"m": {"$ifNull": [{"$first": "$member_stats"}, {}]},
                  "c": {"$ifNull": [{"$first": "$class_stats"}, {}]}}},
        {"$project": {
            "_id": 0, "branch_id": "$_id", "name": 1, "city": "$address.city",
            "members": {"$ifNull": ["$m.total", 0]},
            "active_members": {"$ifNull": ["$m.active", 0]},
            "classes": {"$ifNull": ["$c.classes", 0]},
            "bookings": {"$ifNull": ["$c.bookings", 0]},
            "fill_rate": _percent({"$ifNull": ["$c.bookings", 0]}, {"$ifNull": ["$c.capacity", 0]}),
            "attendance_rate": _percent({"$ifNull": ["$c.attended", 0]}, {"$ifNull": ["$c.past_booked", 0]}),
            "bookings_per_active_member": {"$cond": [
                {"$gt": ["$m.active", 0]},
                {"$round": [{"$divide": ["$c.bookings", "$m.active"]}, 2]}, None]},
        }},
        {"$sort": {"bookings": -1}},
    ]
    data = list(branches.aggregate(pipeline))
    return ok({"data": data, "count": len(data)})


@reports_bp.route("/reports/peak-times", methods=["GET"])
@role_required("admin")
def peak_times():
    args = validate_query({**DATE_RANGE_QUERY,
                           "limit": {"type": "int", "min": 1, "max": 50, "default": 10}})
    day_names = ["", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

    pipeline = [
        {"$match": _class_match(args)},
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
                {"$limit": args["limit"]},
            ],
            "by_weekday": [
                {"$group": {"_id": "$day", "bookings": {"$sum": 1}}},
                {"$sort": {"_id": 1}},
                {"$project": {"_id": 0, "day_number": "$_id", "bookings": 1,
                              "day": {"$arrayElemAt": [day_names, "$_id"]}}},
            ],
            "by_hour": [
                {"$group": {"_id": "$hour", "bookings": {"$sum": 1}}},
                {"$sort": {"_id": 1}},
                {"$project": {"_id": 0, "hour": "$_id", "bookings": 1}},
            ],
        }},
    ]
    result = list(classes.aggregate(pipeline))[0]
    return ok({"timezone": "UTC", **result})


@reports_bp.route("/reports/trainer-performance", methods=["GET"])
@role_required("admin")
def trainer_performance():
    args = validate_query({
        **DATE_RANGE_QUERY,
        "sort": {"type": "string", "choices": ["attendance_rate", "fill_rate", "classes_taught"],
                 "default": "attendance_rate"},
    })
    pipeline = [
        {"$match": _class_match(args)},
        _class_fields(now_utc()),
        {"$group": {"_id": "$trainer_id",
                    "trainer_name": {"$first": "$trainer_name"},
                    "classes_taught": {"$sum": {"$cond": ["$happened", 1, 0]}},
                    "upcoming_classes": {"$sum": {"$cond": ["$happened", 0, 1]}},
                    "bookings": {"$sum": "$booked_count"},
                    "capacity": {"$sum": "$capacity"},
                    "attended": {"$sum": "$attended"},
                    "past_booked": {"$sum": "$past_booked"},
                    "categories": {"$addToSet": "$category"}}},
        # Join the trainer's account for their specialities and home branch
        {"$lookup": {"from": "users", "localField": "_id", "foreignField": "_id",
                     "as": "trainer", "pipeline": [{"$project": {"specialities": 1, "branch_id": 1}}]}},
        {"$lookup": {"from": "branches", "localField": "trainer.branch_id", "foreignField": "_id",
                     "as": "branch", "pipeline": [{"$project": {"name": 1}}]}},
        {"$project": {
            "_id": 0, "trainer_id": "$_id", "trainer_name": 1,
            "branch": {"$first": "$branch.name"},
            "specialities": {"$first": "$trainer.specialities"},
            "categories": 1, "classes_taught": 1, "upcoming_classes": 1, "bookings": 1,
            "fill_rate": _percent("$bookings", "$capacity"),
            "attendance_rate": _percent("$attended", "$past_booked"),
        }},
        {"$sort": {args["sort"]: -1, "trainer_name": 1}},
    ]
    data = list(classes.aggregate(pipeline))
    return ok({"sorted_by": args["sort"], "data": data, "count": len(data)})


@reports_bp.route("/reports/membership-summary", methods=["GET"])
@role_required("admin")
def membership_summary():
    args = validate_query({"days": {"type": "int", "min": 1, "max": 365, "default": 30},
                           "limit": {"type": "int", "min": 1, "max": 100, "default": 20},
                           "branch": {"type": "objectid"}})
    now = now_utc()
    horizon = now + timedelta(days=args["days"])
    match = {"home_branch_id": args["branch"]} if "branch" in args else {}
    expiring = {"membership.end_date": {"$gte": now, "$lte": horizon}}

    # Status is worked out from end_date, so the report is right even for stale documents
    status_expr = {"$cond": [{"$gte": ["$membership.end_date", now]}, "active", "expired"]}
    pipeline = [
        {"$match": match},
        {"$facet": {
            "total": [{"$count": "members"}],
            "by_status": [
                {"$group": {"_id": status_expr, "members": {"$sum": 1}}},
                {"$project": {"_id": 0, "status": "$_id", "members": 1}},
                {"$sort": {"status": 1}},
            ],
            "by_plan": [
                {"$group": {"_id": "$membership.plan",
                            "members": {"$sum": 1},
                            "active": {"$sum": {"$cond": [{"$eq": [status_expr, "active"]}, 1, 0]}}}},
                {"$project": {"_id": 0, "plan": "$_id", "members": 1, "active": 1,
                              "expired": {"$subtract": ["$members", "$active"]}}},
                {"$sort": {"members": -1}},
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
                                                          "unit": "day"}}}},
            ],
        }},
    ]
    result = list(members.aggregate(pipeline))[0]
    return ok({
        "total_members": result["total"][0]["members"] if result["total"] else 0,
        "by_status": result["by_status"],
        "by_plan": result["by_plan"],
        "expiring_soon": {
            "within_days": args["days"],
            "count": result["expiring_count"][0]["members"] if result["expiring_count"] else 0,
            "members": result["expiring_soon"],         # soonest first, up to `limit`
        },
    })
