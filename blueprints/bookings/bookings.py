from bson import ObjectId
from flask import Blueprint, g, jsonify, make_response, request

from decorators import jwt_required, role_required
import globals
from utils.validation import now_utc, validate_body, validate_query

bookings_bp = Blueprint("bookings", __name__)

# bookings are stored inside each class document


# BOOK A PLACE - member accounts only
@bookings_bp.route("/api/v1.0/classes/<string:id>/bookings", methods=["POST"])
@jwt_required
def add_new_booking(id):
    if g.user["member_id"] is None:
        return make_response(jsonify({"error": "Only member accounts can do this",
                                      "details": {"your_role": g.user["role"]}}), 403)
    member_id = ObjectId(g.user["member_id"])

    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid class ID"}), 400)
    cls = globals.db.classes.find_one({"_id": ObjectId(id)}, {"start_time": 1})
    if cls is None:
        return make_response(jsonify({"error": "Class not found"}), 404)

    member = globals.db.members.find_one({"_id": member_id}, {"name": 1, "membership": 1})
    if member is None:
        return make_response(jsonify({"error": "Your member record no longer exists"}), 404)

    end_date = (member.get("membership") or {}).get("end_date")
    if not end_date or end_date < now_utc():
        return make_response(jsonify({"error": "Your membership is not active",
                                      "details": {"membership_end_date": end_date}}), 403)
    if end_date < cls["start_time"]:
        return make_response(jsonify({"error": "Your membership ends before this class starts",
                                      "details": {"membership_end_date": end_date,
                                                  "class_start_time": cls["start_time"]}}), 403)

    new_booking = {
        "_id": ObjectId(),
        "member_id": member_id,
        "member_name": member["name"],
        "booked_at": now_utc(),
        "status": "booked",
        "attended": None
    }

    # every rule is in the filter of one update_one, so MongoDB checks and books
    # in a single step and two members can never both take the last place
    result = globals.db.classes.update_one(
        {
            "_id": cls["_id"],
            "status": "scheduled",
            "start_time": {"$gt": now_utc()},
            "$expr": {"$lt": ["$booked_count", "$capacity"]},          # a place is free
            "bookings": {"$not": {"$elemMatch": {"member_id": member_id, "status": "booked"}}}
        },
        {"$push": {"bookings": new_booking}, "$inc": {"booked_count": 1}}
    )

    if result.modified_count == 0:
        # nothing was booked, so read the class again to say which rule failed
        current = globals.db.classes.find_one({"_id": cls["_id"]}, {
            "status": 1, "start_time": 1, "capacity": 1, "booked_count": 1,
            "bookings": {"$elemMatch": {"member_id": member_id, "status": "booked"}}})
        if current["status"] == "cancelled":
            return make_response(jsonify({"error": "This class has been cancelled"}), 400)
        if current["status"] == "completed" or current["start_time"] <= now_utc():
            return make_response(jsonify({"error": "This class has already started or taken place"}), 400)
        if current.get("bookings"):
            return make_response(jsonify({"error": "You have already booked this class",
                                          "details": {"booking_id": current["bookings"][0]["_id"]}}), 409)
        if current["booked_count"] >= current["capacity"]:
            return make_response(jsonify({"error": "This class is full",
                                          "details": {"capacity": current["capacity"]}}), 409)
        return make_response(jsonify({"error": "The class changed while booking, please try again"}), 409)

    updated = globals.db.classes.find_one({"_id": cls["_id"]}, {"capacity": 1, "booked_count": 1})
    new_booking_link = request.host_url + "api/v1.0/classes/" + id + "/bookings/" + str(new_booking["_id"])
    response = make_response(jsonify({"message": "Class booked", "id": str(new_booking["_id"]),
                                    "url": new_booking_link,
                                    "spaces_left": updated["capacity"] - updated["booked_count"]}), 201)
    response.headers["Location"] = new_booking_link
    return response


# admin or the class's own trainer
@bookings_bp.route("/api/v1.0/classes/<string:id>/bookings", methods=["GET"])
@role_required("admin", "trainer")
def show_all_bookings(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid class ID"}), 400)
    cls = globals.db.classes.find_one({"_id": ObjectId(id)})
    if cls is None:
        return make_response(jsonify({"error": "Class not found"}), 404)
    if g.user["role"] != "admin" and str(cls["trainer_id"]) != g.user["user_id"]:
        return make_response(jsonify({"error": "Only an admin or the class's own trainer can do this"}), 403)

    args, errors = validate_query({"status": {"type": "string", "choices": globals.OPTIONS["booking_statuses"]}})
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)

    bookings = cls["bookings"]
    data = []
    for booking in bookings:
        if "status" not in args or booking["status"] == args["status"]:
            data.append(booking)
    data.sort(key=lambda booking: booking["booked_at"])

    summary = {"booked": 0, "cancelled": 0, "attended": 0, "no_shows": 0}
    for booking in bookings:
        summary[booking["status"]] += 1
        if booking["attended"] is True:
            summary["attended"] += 1
        elif booking["attended"] is False:
            summary["no_shows"] += 1

    return make_response(jsonify({
        "class": {"_id": cls["_id"], "title": cls["title"], "start_time": cls["start_time"],
                  "capacity": cls["capacity"], "booked_count": cls["booked_count"], "status": cls["status"]},
        "data": data,
        "count": len(data),
        "summary": summary
    }), 200)


# the member who booked, the class's trainer or an admin
@bookings_bp.route("/api/v1.0/classes/<string:id>/bookings/<string:booking_id>", methods=["GET"])
@jwt_required
def show_one_booking(id, booking_id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid class ID"}), 400)
    cls = globals.db.classes.find_one({"_id": ObjectId(id)}, {"bookings": 0})
    if cls is None:
        return make_response(jsonify({"error": "Class not found"}), 404)
    if not ObjectId.is_valid(booking_id):
        return make_response(jsonify({"error": "Invalid booking ID"}), 400)
    # "bookings.$" returns only the booking that matched
    found = globals.db.classes.find_one({"_id": cls["_id"], "bookings._id": ObjectId(booking_id)}, {"bookings.$": 1})
    if found is None:
        return make_response(jsonify({"error": "Booking not found"}), 404)
    booking = found["bookings"][0]

    if g.user["member_id"] != str(booking["member_id"]) and g.user["role"] != "admin" and \
            str(cls["trainer_id"]) != g.user["user_id"]:
        return make_response(jsonify({"error": "Only an admin or the class's own trainer can do this"}), 403)

    booking["class"] = {"_id": cls["_id"], "title": cls["title"], "start_time": cls["start_time"],
                        "branch_name": cls["branch_name"], "status": cls["status"]}
    return make_response(jsonify(booking), 200)


# CANCEL A BOOKING - the member who booked, the class's trainer or an admin
@bookings_bp.route("/api/v1.0/classes/<string:id>/bookings/<string:booking_id>", methods=["DELETE"])
@jwt_required
def cancel_booking(id, booking_id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid class ID"}), 400)
    cls = globals.db.classes.find_one({"_id": ObjectId(id)}, {"bookings": 0})
    if cls is None:
        return make_response(jsonify({"error": "Class not found"}), 404)
    if not ObjectId.is_valid(booking_id):
        return make_response(jsonify({"error": "Invalid booking ID"}), 400)
    found = globals.db.classes.find_one({"_id": cls["_id"], "bookings._id": ObjectId(booking_id)}, {"bookings.$": 1})
    if found is None:
        return make_response(jsonify({"error": "Booking not found"}), 404)
    booking = found["bookings"][0]

    if g.user["member_id"] != str(booking["member_id"]) and g.user["role"] != "admin" and \
            str(cls["trainer_id"]) != g.user["user_id"]:
        return make_response(jsonify({"error": "Only an admin or the class's own trainer can do this"}), 403)
    if booking["status"] == "cancelled":
        return make_response(jsonify({"error": "This booking is already cancelled"}), 409)

    # same idea as booking: the rules are in the filter, and the status change and
    # the booked_count decrease happen in one update
    result = globals.db.classes.update_one(
        {"_id": cls["_id"], "status": "scheduled", "start_time": {"$gt": now_utc()},
         "bookings": {"$elemMatch": {"_id": booking["_id"], "status": "booked"}}},
        {"$set": {"bookings.$.status": "cancelled"}, "$inc": {"booked_count": -1}}
    )
    if result.modified_count == 0:
        return make_response(jsonify({"error": "Bookings can only be cancelled before a scheduled class starts"}), 400)
    return make_response(jsonify({"message": "Booking cancelled", "booking_id": booking["_id"]}), 200)


# MARK ATTENDANCE - admin or the class's own trainer, once the class has started
@bookings_bp.route("/api/v1.0/classes/<string:id>/bookings/<string:booking_id>/attendance", methods=["PUT"])
@role_required("admin", "trainer")
def edit_attendance(id, booking_id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid class ID"}), 400)
    cls = globals.db.classes.find_one({"_id": ObjectId(id)}, {"bookings": 0})
    if cls is None:
        return make_response(jsonify({"error": "Class not found"}), 404)
    if not ObjectId.is_valid(booking_id):
        return make_response(jsonify({"error": "Invalid booking ID"}), 400)
    found = globals.db.classes.find_one({"_id": cls["_id"], "bookings._id": ObjectId(booking_id)}, {"bookings.$": 1})
    if found is None:
        return make_response(jsonify({"error": "Booking not found"}), 404)
    booking = found["bookings"][0]

    if g.user["role"] != "admin" and str(cls["trainer_id"]) != g.user["user_id"]:
        return make_response(jsonify({"error": "Only an admin or the class's own trainer can do this"}), 403)

    data, errors = validate_body(globals.SCHEMAS["attendance"])
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)

    if cls["status"] == "cancelled":
        return make_response(jsonify({"error": "This class was cancelled"}), 400)
    if cls["start_time"] > now_utc():
        return make_response(jsonify({"error": "Attendance can only be recorded once the class has started",
                                      "details": {"start_time": cls["start_time"]}}), 400)
    if booking["status"] != "booked":
        return make_response(jsonify({"error": "Attendance cannot be recorded for a cancelled booking"}), 400)

    updates = {"bookings.$.attended": data["attended"]}
    if cls["status"] == "scheduled":
        updates["status"] = "completed"       # recording attendance means the class took place
    globals.db.classes.update_one({"_id": cls["_id"], "bookings._id": booking["_id"]}, {"$set": updates})

    found = globals.db.classes.find_one({"_id": cls["_id"], "bookings._id": booking["_id"]}, {"bookings.$": 1})
    return make_response(jsonify({"message": "Attendance recorded", "booking": found["bookings"][0]}), 200)
