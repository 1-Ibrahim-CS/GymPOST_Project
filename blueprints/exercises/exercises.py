import math
import re

from bson import ObjectId
from flask import Blueprint, jsonify, make_response, request

from decorators import role_required
from globals import exercises
from utils.constants import BODY_PARTS, EQUIPMENT, EXERCISE_LEVELS, EXERCISE_TYPES, PAGINATION_QUERY
from utils.validation import validate_body, validate_query

exercises_bp = Blueprint("exercises", __name__)

EXERCISE_SCHEMA = {
    "title": {"type": "string", "required": True, "min_len": 3, "max_len": 120},
    "description": {"type": "string", "nullable": True, "max_len": 2000},
    "type": {"type": "string", "required": True, "choices": EXERCISE_TYPES},
    "body_part": {"type": "string", "required": True, "choices": BODY_PARTS},
    "equipment": {"type": "string", "required": True, "choices": EQUIPMENT},
    "level": {"type": "string", "required": True, "choices": EXERCISE_LEVELS},
    "rating": {"type": "number", "nullable": True, "min": 0, "max": 10},
}

# filters that take comma-separated values, e.g. ?body_part=Chest,Triceps
LIST_FILTERS = {"body_part": BODY_PARTS, "equipment": EQUIPMENT, "level": EXERCISE_LEVELS,
                "type": EXERCISE_TYPES}


@exercises_bp.route("/api/v1.0/exercises", methods=["GET"])
def show_all_exercises():
    query_rules = {
        "min_rating": {"type": "number", "min": 0, "max": 10},
        "q": {"type": "string", "max_len": 100},
        "sort": {"type": "string", "choices": ["rating", "title", "reviews"]},
        "order": {"type": "string", "choices": ["asc", "desc"]},
        **PAGINATION_QUERY
    }
    for field, values in LIST_FILTERS.items():
        query_rules[field] = {"type": "list", "items": {"type": "string", "choices": values}}
    args, errors = validate_query(query_rules)
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)

    match = {}
    if "q" in args:
        match["$text"] = {"$search": args["q"]}       # text index on title + description
    for field in LIST_FILTERS:
        if field in args:
            match[field] = {"$in": args[field]}
    if "min_rating" in args:
        match["rating"] = {"$gte": args["min_rating"]}

    # default order: best match when searching, otherwise A-Z by title
    if "sort" in args:
        sort_field = args["sort"]
    elif "q" in args:
        sort_field = "relevance"
    else:
        sort_field = "title"
    default_order = "asc" if sort_field == "title" else "desc"
    direction = 1 if args.get("order", default_order) == "asc" else -1

    if sort_field == "relevance":
        sort = {"score": {"$meta": "textScore"}}
    elif sort_field == "rating":
        sort = {"rating": direction, "title": 1}
    elif sort_field == "reviews":
        sort = {"review_count": direction, "title": 1}
    else:
        sort = {"title": direction}

    page_start = args["ps"] * (args["pn"] - 1)
    pipeline = [
        {"$match": match},
        {"$addFields": {"review_count": {"$size": "$reviews"},
                        "avg_stars": {"$round": [{"$avg": "$reviews.stars"}, 2]}}},
        {"$project": {"reviews": 0}},
        {"$sort": sort},
        # one page of results and the total count in the same query
        {"$facet": {"data": [{"$skip": page_start}, {"$limit": args["ps"]}],
                    "total": [{"$count": "count"}]}}
    ]
    if "q" in args:
        result = list(exercises.aggregate(pipeline))[0]
    else:
        # case-insensitive title order ($text search can't be used with a collation)
        result = list(exercises.aggregate(pipeline, collation={"locale": "en", "strength": 2}))[0]

    total = result["total"][0]["count"] if result["total"] else 0
    pagination = {"page": args["pn"], "page_size": args["ps"], "total": total,
                  "pages": math.ceil(total / args["ps"])}
    return make_response(jsonify({"data": result["data"], "pagination": pagination}), 200)


@exercises_bp.route("/api/v1.0/exercises", methods=["POST"])
@role_required("admin", "trainer")
def add_new_exercise():
    data, errors = validate_body(EXERCISE_SCHEMA)
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)

    title_query = {"title": {"$regex": "^" + re.escape(data["title"]) + "$", "$options": "i"}}
    if exercises.find_one(title_query) is not None:
        return make_response(jsonify({"error": "An exercise with this title already exists"}), 409)

    data.setdefault("description", None)
    data.setdefault("rating", None)
    data["reviews"] = []
    new_id = exercises.insert_one(data).inserted_id

    new_exercise_link = request.host_url + "api/v1.0/exercises/" + str(new_id)
    response = make_response(jsonify({"message": "Exercise created", "id": str(new_id), "url": new_exercise_link}), 201)
    response.headers["Location"] = new_exercise_link
    return response


# every value of each filter with how many exercises have it
@exercises_bp.route("/api/v1.0/exercises/filters", methods=["GET"])
def show_exercise_filters():
    facets = {}
    for field in LIST_FILTERS:
        facets[field] = [{"$sortByCount": "$" + field},
                         {"$project": {"_id": 0, "value": "$_id", "count": 1}}]
    result = list(exercises.aggregate([{"$facet": facets}]))[0]
    return make_response(jsonify(result), 200)


# best average review stars
@exercises_bp.route("/api/v1.0/exercises/top-rated", methods=["GET"])
def show_top_rated():
    args, errors = validate_query({
        "body_part": {"type": "list", "items": {"type": "string", "choices": BODY_PARTS}},
        "min_reviews": {"type": "int", "min": 1, "max": 50, "default": 2},
        "limit": {"type": "int", "min": 1, "max": 50, "default": 10}
    })
    if errors:
        return make_response(jsonify({"error": "Invalid query parameters", "details": errors}), 400)

    match = {"reviews.0": {"$exists": True}}          # at least one review
    if "body_part" in args:
        match["body_part"] = {"$in": args["body_part"]}
    pipeline = [
        {"$match": match},
        {"$project": {
            "title": 1, "body_part": 1, "equipment": 1, "level": 1, "type": 1,
            "review_count": {"$size": "$reviews"},
            "avg_stars": {"$avg": "$reviews.stars"}
        }},
        # one 5-star review is not "top rated", so ignore exercises with too few reviews
        {"$match": {"review_count": {"$gte": args["min_reviews"]}}},
        {"$sort": {"avg_stars": -1, "review_count": -1, "title": 1}},
        {"$limit": args["limit"]},
        {"$set": {"avg_stars": {"$round": ["$avg_stars", 2]}}}
    ]
    results = list(exercises.aggregate(pipeline))
    return make_response(jsonify({"data": results, "count": len(results),
                                  "min_reviews": args["min_reviews"]}), 200)


@exercises_bp.route("/api/v1.0/exercises/<string:id>", methods=["GET"])
def show_one_exercise(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid exercise ID"}), 400)
    exercise = exercises.find_one({"_id": ObjectId(id)})
    if exercise is None:
        return make_response(jsonify({"error": "Exercise not found"}), 404)

    stars = [review["stars"] for review in exercise["reviews"]]
    exercise["review_count"] = len(stars)
    exercise["avg_stars"] = round(sum(stars) / len(stars), 2) if stars else None
    return make_response(jsonify(exercise), 200)


@exercises_bp.route("/api/v1.0/exercises/<string:id>", methods=["PUT"])
@role_required("admin", "trainer")
def edit_exercise(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid exercise ID"}), 400)
    exercise = exercises.find_one({"_id": ObjectId(id)}, {"_id": 1})
    if exercise is None:
        return make_response(jsonify({"error": "Exercise not found"}), 404)

    data, errors = validate_body(EXERCISE_SCHEMA, partial=True)
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)

    if "title" in data:
        title_query = {"title": {"$regex": "^" + re.escape(data["title"]) + "$", "$options": "i"},
                       "_id": {"$ne": exercise["_id"]}}
        if exercises.find_one(title_query) is not None:
            return make_response(jsonify({"error": "An exercise with this title already exists"}), 409)

    exercises.update_one({"_id": exercise["_id"]}, {"$set": data})
    return make_response(jsonify({"message": "Exercise updated",
                                  "exercise": exercises.find_one({"_id": exercise["_id"]}, {"reviews": 0})}), 200)


@exercises_bp.route("/api/v1.0/exercises/<string:id>", methods=["DELETE"])
@role_required("admin", "trainer")
def delete_exercise(id):
    if not ObjectId.is_valid(id):
        return make_response(jsonify({"error": "Invalid exercise ID"}), 400)
    result = exercises.delete_one({"_id": ObjectId(id)})
    if result.deleted_count == 0:
        return make_response(jsonify({"error": "Exercise not found"}), 404)
    # workout logs keep their own copy of the title, so old workouts still read fine
    return make_response(jsonify({}), 204)
