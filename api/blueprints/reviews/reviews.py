from bson import ObjectId
from flask import Blueprint, g, jsonify, make_response, request

from decorators import jwt_required
import globals
from utils.validation import now_utc, validate_body, validate_query

reviews_bp = Blueprint("reviews", __name__)

# reviews are stored inside each exercise document


@reviews_bp.route("/api/v1.0/exercises/<string:id>/reviews", methods=["GET"])
def show_all_reviews(id):
    args, errors = validate_query({"sort": {"type": "string", "choices": ["newest", "oldest", "stars"],
                                            "default": "newest"}})
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid exercise ID"}), 400)
    exercise = globals.db.exercises.find_one({"_id": ObjectId(id)}, {"title": 1, "reviews": 1})
    if exercise is None:
        return make_response(jsonify({"error": "Exercise not found"}), 404)

    reviews = exercise["reviews"]
    if args["sort"] == "stars":
        reviews.sort(key=lambda review: (review["stars"], review["created_at"]), reverse=True)
    else:
        reviews.sort(key=lambda review: review["created_at"], reverse=args["sort"] == "newest")

    stars = [review["stars"] for review in reviews]
    return make_response(jsonify({
        "exercise": {"_id": exercise["_id"], "title": exercise["title"]},
        "data": reviews,
        "count": len(reviews),
        "avg_stars": round(sum(stars) / len(stars), 2) if stars else None
    }), 200)


# members only - one review per member per exercise
@reviews_bp.route("/api/v1.0/exercises/<string:id>/reviews", methods=["POST"])
@jwt_required
def add_new_review(id):
    if g.user["member_id"] is None:
        return make_response(jsonify({"error": "Only member accounts can do this",
                                      "details": {"your_role": g.user["role"]}}), 403)
    member_id = ObjectId(g.user["member_id"])

    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid exercise ID"}), 400)
    exercise = globals.db.exercises.find_one({"_id": ObjectId(id)}, {"_id": 1})
    if exercise is None:
        return make_response(jsonify({"error": "Exercise not found"}), 404)

    data, errors = validate_body(globals.SCHEMAS["review"])
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)

    member = globals.db.members.find_one({"_id": member_id}, {"name": 1})
    if member is None:
        return make_response(jsonify({"error": "Your member record no longer exists"}), 404)

    new_review = {
        "_id": ObjectId(),
        "member_id": member_id,
        "member_name": member["name"],
        "stars": data["stars"],
        "comment": data["comment"],
        "created_at": now_utc()
    }
    # the "not already reviewed" check is part of the update filter,
    # so two requests at the same time can't both add a review
    result = globals.db.exercises.update_one(
        {"_id": exercise["_id"], "reviews.member_id": {"$ne": member_id}},
        {"$push": {"reviews": new_review}}
    )
    if result.modified_count == 0:
        return make_response(jsonify({"error": "You have already reviewed this exercise",
                                      "details": {"hint": "Edit your existing review with PUT instead"}}), 409)

    new_review_link = request.host_url + "api/v1.0/exercises/" + id + "/reviews/" + str(new_review["_id"])
    response = make_response(jsonify({"message": "Review added", "id": str(new_review["_id"]),
                                    "url": new_review_link}), 201)
    response.headers["Location"] = new_review_link
    return response


@reviews_bp.route("/api/v1.0/exercises/<string:id>/reviews/<string:review_id>", methods=["GET"])
def show_one_review(id, review_id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid exercise ID"}), 400)
    if globals.db.exercises.find_one({"_id": ObjectId(id)}, {"_id": 1}) is None:
        return make_response(jsonify({"error": "Exercise not found"}), 404)
    if not ObjectId.is_valid(review_id):
        return make_response(jsonify({"error": "Invalid review ID"}), 400)

    # "reviews.$" returns only the review that matched
    exercise = globals.db.exercises.find_one({"_id": ObjectId(id), "reviews._id": ObjectId(review_id)},
                                             {"reviews.$": 1})
    if exercise is None:
        return make_response(jsonify({"error": "Review not found"}), 404)
    return make_response(jsonify(exercise["reviews"][0]), 200)


# only the author can edit a review
@reviews_bp.route("/api/v1.0/exercises/<string:id>/reviews/<string:review_id>", methods=["PUT"])
@jwt_required
def edit_review(id, review_id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid exercise ID"}), 400)
    if globals.db.exercises.find_one({"_id": ObjectId(id)}, {"_id": 1}) is None:
        return make_response(jsonify({"error": "Exercise not found"}), 404)
    if not ObjectId.is_valid(review_id):
        return make_response(jsonify({"error": "Invalid review ID"}), 400)
    exercise = globals.db.exercises.find_one({"_id": ObjectId(id), "reviews._id": ObjectId(review_id)},
                                             {"reviews.$": 1})
    if exercise is None:
        return make_response(jsonify({"error": "Review not found"}), 404)

    review = exercise["reviews"][0]
    if g.user["member_id"] != str(review["member_id"]):
        return make_response(jsonify({"error": "You can only change your own reviews"}), 403)

    data, errors = validate_body(globals.SCHEMAS["review"], partial=True)
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)

    # "reviews.$" updates the review matched by reviews._id
    updates = {"reviews.$.updated_at": now_utc()}
    for field, value in data.items():
        updates["reviews.$." + field] = value
    globals.db.exercises.update_one({"_id": ObjectId(id), "reviews._id": review["_id"]}, {"$set": updates})

    exercise = globals.db.exercises.find_one({"_id": ObjectId(id), "reviews._id": review["_id"]}, {"reviews.$": 1})
    return make_response(jsonify({"message": "Review updated", "review": exercise["reviews"][0]}), 200)


# the author or an admin (moderation) can delete a review
@reviews_bp.route("/api/v1.0/exercises/<string:id>/reviews/<string:review_id>", methods=["DELETE"])
@jwt_required
def delete_review(id, review_id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid exercise ID"}), 400)
    if globals.db.exercises.find_one({"_id": ObjectId(id)}, {"_id": 1}) is None:
        return make_response(jsonify({"error": "Exercise not found"}), 404)
    if not ObjectId.is_valid(review_id):
        return make_response(jsonify({"error": "Invalid review ID"}), 400)
    exercise = globals.db.exercises.find_one({"_id": ObjectId(id), "reviews._id": ObjectId(review_id)},
                                             {"reviews.$": 1})
    if exercise is None:
        return make_response(jsonify({"error": "Review not found"}), 404)

    review = exercise["reviews"][0]
    if g.user["role"] != "admin" and g.user["member_id"] != str(review["member_id"]):
        return make_response(jsonify({"error": "You can only change your own reviews"}), 403)

    globals.db.exercises.update_one({"_id": ObjectId(id)}, {"$pull": {"reviews": {"_id": review["_id"]}}})
    return make_response(jsonify({}), 204)
