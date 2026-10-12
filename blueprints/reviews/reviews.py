"""
reviews Blueprint - member reviews embedded in each exercise document (sub-documents).

    GET    /api/v1.0/exercises/<id>/reviews                all reviews + average
    POST   /api/v1.0/exercises/<id>/reviews                add a review          (member)
    GET    /api/v1.0/exercises/<id>/reviews/<review_id>    one review
    PUT    /api/v1.0/exercises/<id>/reviews/<review_id>    edit                  (review author)
    DELETE /api/v1.0/exercises/<id>/reviews/<review_id>    delete                (author or admin)
"""

from bson import ObjectId
from flask import Blueprint, g

from blueprints.exercises.exercises import find_exercise
from decorators import current_member_id, is_admin, jwt_required
from globals import exercises, members
from utils.errors import ApiError
from utils.responses import created, no_content, ok
from utils.validation import now_utc, parse_object_id, validate_body, validate_query

reviews_bp = Blueprint("reviews", __name__)

REVIEW_SCHEMA = {
    "stars": {"type": "int", "required": True, "min": 1, "max": 5},
    "comment": {"type": "string", "required": True, "min_len": 2, "max_len": 500},
}


def _find_review(exercise_id, review_id):
    """Returns (exercise_id, review). 404 tells apart a missing exercise and a missing review."""
    exercise = find_exercise(exercise_id, {"_id": 1})
    rid = parse_object_id(review_id, "review id")
    # The positional projection "reviews.$" returns only the matching array element
    doc = exercises.find_one({"_id": exercise["_id"], "reviews._id": rid}, {"reviews.$": 1})
    if not doc:
        raise ApiError(404, "Review not found")
    return exercise["_id"], doc["reviews"][0]


def _ensure_author(review):
    if g.user.get("member_id") != str(review["member_id"]):
        raise ApiError(403, "You can only change your own reviews")


@reviews_bp.route("/exercises/<id>/reviews", methods=["GET"])
def list_reviews(id):
    args = validate_query({"sort": {"type": "string", "choices": ["newest", "oldest", "stars"],
                                    "default": "newest"}})
    exercise = find_exercise(id, {"title": 1, "reviews": 1})
    reviews = exercise["reviews"]
    if args["sort"] == "stars":
        reviews.sort(key=lambda r: (r["stars"], r["created_at"]), reverse=True)
    else:
        reviews.sort(key=lambda r: r["created_at"], reverse=args["sort"] == "newest")
    stars = [r["stars"] for r in reviews]
    return ok({
        "exercise": {"_id": exercise["_id"], "title": exercise["title"]},
        "data": reviews,
        "count": len(reviews),
        "avg_stars": round(sum(stars) / len(stars), 2) if stars else None,
    })


@reviews_bp.route("/exercises/<id>/reviews", methods=["POST"])
@jwt_required
def add_review(id):
    member_id = current_member_id()                # staff accounts can't review
    exercise = find_exercise(id, {"_id": 1})
    data = validate_body(REVIEW_SCHEMA)
    member = members.find_one({"_id": member_id}, {"name": 1})
    if not member:
        raise ApiError(404, "Your member record no longer exists")

    review = {"_id": ObjectId(), "member_id": member_id, "member_name": member["name"],
              "stars": data["stars"], "comment": data["comment"], "created_at": now_utc()}
    # One review per member per exercise. The check is part of the update filter,
    # so two requests at the same moment cannot both add a review.
    result = exercises.update_one(
        {"_id": exercise["_id"], "reviews.member_id": {"$ne": member_id}},
        {"$push": {"reviews": review}},
    )
    if result.modified_count == 0:
        raise ApiError(409, "You have already reviewed this exercise",
                       {"hint": "Edit your existing review with PUT instead"})
    return created("Review added", review["_id"], "reviews.get_review",
                   id=exercise["_id"], review_id=review["_id"])


@reviews_bp.route("/exercises/<id>/reviews/<review_id>", methods=["GET"])
def get_review(id, review_id):
    return ok(_find_review(id, review_id)[1])


@reviews_bp.route("/exercises/<id>/reviews/<review_id>", methods=["PUT"])
@jwt_required
def update_review(id, review_id):
    exercise_id, review = _find_review(id, review_id)
    _ensure_author(review)
    data = validate_body(REVIEW_SCHEMA, partial=True)
    # "reviews.$" is the positional operator: it updates the element matched by reviews._id
    updates = {f"reviews.$.{field}": value for field, value in data.items()}
    updates["reviews.$.updated_at"] = now_utc()
    exercises.update_one({"_id": exercise_id, "reviews._id": review["_id"]}, {"$set": updates})
    return ok({"message": "Review updated", "review": _find_review(id, review_id)[1]})


@reviews_bp.route("/exercises/<id>/reviews/<review_id>", methods=["DELETE"])
@jwt_required
def delete_review(id, review_id):
    exercise_id, review = _find_review(id, review_id)
    if not is_admin():                       # admins can moderate any review
        _ensure_author(review)
    exercises.update_one({"_id": exercise_id}, {"$pull": {"reviews": {"_id": review["_id"]}}})
    return no_content()
