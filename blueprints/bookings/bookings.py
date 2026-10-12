"""
bookings Blueprint - class bookings embedded in each class document (sub-documents).

    POST   /api/v1.0/classes/<id>/bookings                           book a place       (member)
    GET    /api/v1.0/classes/<id>/bookings                           list               (admin, class trainer)
    GET    /api/v1.0/classes/<id>/bookings/<booking_id>              one booking        (admin, class trainer, booker)
    DELETE /api/v1.0/classes/<id>/bookings/<booking_id>              cancel             (admin, class trainer, booker)
    PUT    /api/v1.0/classes/<id>/bookings/<booking_id>/attendance   mark attendance    (admin, class trainer)
"""

from bson import ObjectId
from flask import Blueprint, g

from blueprints.classes.classes import ensure_can_manage, find_class
from decorators import current_member_id, jwt_required, role_required
from globals import classes, members
from utils.constants import BOOKING_STATUSES
from utils.errors import ApiError
from utils.responses import created, ok
from utils.validation import now_utc, parse_object_id, validate_body, validate_query

bookings_bp = Blueprint("bookings", __name__)


def _find_booking(class_id, booking_id):
    """Returns (class without bookings, booking)."""
    cls = find_class(class_id, {"bookings": 0})
    bid = parse_object_id(booking_id, "booking id")
    doc = classes.find_one({"_id": cls["_id"], "bookings._id": bid}, {"bookings.$": 1})
    if not doc:
        raise ApiError(404, "Booking not found")
    return cls, doc["bookings"][0]


def _ensure_booking_access(cls, booking):
    """The member who made the booking, the class's trainer or an admin."""
    if g.user.get("member_id") == str(booking["member_id"]):
        return
    ensure_can_manage(cls)


@bookings_bp.route("/classes/<id>/bookings", methods=["POST"])
@jwt_required
def book_class(id):
    member_id = current_member_id()                  # only member accounts can book
    cls = find_class(id, {"start_time": 1})
    member = members.find_one({"_id": member_id}, {"name": 1, "membership": 1})
    if not member:
        raise ApiError(404, "Your member record no longer exists")

    end_date = (member.get("membership") or {}).get("end_date")
    if not end_date or end_date < now_utc():
        raise ApiError(403, "Your membership is not active", {"membership_end_date": end_date})
    if end_date < cls["start_time"]:
        raise ApiError(403, "Your membership ends before this class starts",
                       {"membership_end_date": end_date, "class_start_time": cls["start_time"]})

    booking = {"_id": ObjectId(), "member_id": member_id, "member_name": member["name"],
               "booked_at": now_utc(), "status": "booked", "attended": None}

    # ATOMIC BOOKING: every rule is part of the filter of a single update_one.
    # MongoDB checks the filter and applies the update to the document as one
    # operation, so two members can never both take the last place.
    result = classes.update_one(
        {
            "_id": cls["_id"],
            "status": "scheduled",
            "start_time": {"$gt": now_utc()},
            "$expr": {"$lt": ["$booked_count", "$capacity"]},          # a place is free
            "bookings": {"$not": {"$elemMatch": {"member_id": member_id, "status": "booked"}}},
        },
        {"$push": {"bookings": booking}, "$inc": {"booked_count": 1}},
    )

    if result.modified_count == 0:
        # Nothing changed, so one of the rules failed - read the class to say which one
        current = classes.find_one({"_id": cls["_id"]}, {
            "status": 1, "start_time": 1, "capacity": 1, "booked_count": 1,
            "bookings": {"$elemMatch": {"member_id": member_id, "status": "booked"}}})
        if current["status"] == "cancelled":
            raise ApiError(400, "This class has been cancelled")
        if current["status"] == "completed" or current["start_time"] <= now_utc():
            raise ApiError(400, "This class has already started or taken place")
        if current.get("bookings"):
            raise ApiError(409, "You have already booked this class",
                           {"booking_id": current["bookings"][0]["_id"]})
        if current["booked_count"] >= current["capacity"]:
            raise ApiError(409, "This class is full", {"capacity": current["capacity"]})
        raise ApiError(409, "The class changed while booking, please try again")

    updated = classes.find_one({"_id": cls["_id"]}, {"capacity": 1, "booked_count": 1})
    return created("Class booked", booking["_id"], "bookings.get_booking",
                   extra={"spaces_left": updated["capacity"] - updated["booked_count"]},
                   id=cls["_id"], booking_id=booking["_id"])


@bookings_bp.route("/classes/<id>/bookings", methods=["GET"])
@role_required("admin", "trainer")
def list_bookings(id):
    cls = find_class(id)
    ensure_can_manage(cls)
    args = validate_query({"status": {"type": "string", "choices": BOOKING_STATUSES}})
    bookings = cls.pop("bookings")
    data = [b for b in bookings if "status" not in args or b["status"] == args["status"]]
    data.sort(key=lambda b: b["booked_at"])
    return ok({
        "class": {"_id": cls["_id"], "title": cls["title"], "start_time": cls["start_time"],
                  "capacity": cls["capacity"], "booked_count": cls["booked_count"],
                  "status": cls["status"]},
        "data": data,
        "count": len(data),
        "summary": {
            "booked": sum(b["status"] == "booked" for b in bookings),
            "cancelled": sum(b["status"] == "cancelled" for b in bookings),
            "attended": sum(b["attended"] is True for b in bookings),
            "no_shows": sum(b["attended"] is False for b in bookings),
        },
    })


@bookings_bp.route("/classes/<id>/bookings/<booking_id>", methods=["GET"])
@jwt_required
def get_booking(id, booking_id):
    cls, booking = _find_booking(id, booking_id)
    _ensure_booking_access(cls, booking)
    return ok({**booking, "class": {"_id": cls["_id"], "title": cls["title"],
                                    "start_time": cls["start_time"], "branch_name": cls["branch_name"],
                                    "status": cls["status"]}})


@bookings_bp.route("/classes/<id>/bookings/<booking_id>", methods=["DELETE"])
@jwt_required
def cancel_booking(id, booking_id):
    cls, booking = _find_booking(id, booking_id)
    _ensure_booking_access(cls, booking)
    if booking["status"] == "cancelled":
        raise ApiError(409, "This booking is already cancelled")

    # Same idea as booking: the rules are in the filter, and the status change and the
    # booked_count decrement happen in one atomic update. "bookings.$" is the element
    # matched by the $elemMatch.
    result = classes.update_one(
        {"_id": cls["_id"], "status": "scheduled", "start_time": {"$gt": now_utc()},
         "bookings": {"$elemMatch": {"_id": booking["_id"], "status": "booked"}}},
        {"$set": {"bookings.$.status": "cancelled"}, "$inc": {"booked_count": -1}},
    )
    if result.modified_count == 0:
        raise ApiError(400, "Bookings can only be cancelled before a scheduled class starts")
    return ok({"message": "Booking cancelled", "booking_id": booking["_id"]})


@bookings_bp.route("/classes/<id>/bookings/<booking_id>/attendance", methods=["PUT"])
@role_required("admin", "trainer")
def mark_attendance(id, booking_id):
    cls, booking = _find_booking(id, booking_id)
    ensure_can_manage(cls)
    data = validate_body({"attended": {"type": "bool", "required": True}})

    if cls["status"] == "cancelled":
        raise ApiError(400, "This class was cancelled")
    if cls["start_time"] > now_utc():
        raise ApiError(400, "Attendance can only be recorded once the class has started",
                       {"start_time": cls["start_time"]})
    if booking["status"] != "booked":
        raise ApiError(400, "Attendance cannot be recorded for a cancelled booking")

    updates = {"bookings.$.attended": data["attended"]}
    if cls["status"] == "scheduled":
        updates["status"] = "completed"       # recording attendance means the class took place
    classes.update_one({"_id": cls["_id"], "bookings._id": booking["_id"]}, {"$set": updates})
    return ok({"message": "Attendance recorded", "booking": _find_booking(id, booking_id)[1]})
