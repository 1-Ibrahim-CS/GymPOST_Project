"""
exercises Blueprint - the exercise library.

    GET    /api/v1.0/exercises               search, filter, sort and paginate
    POST   /api/v1.0/exercises               create              (admin, trainer)
    GET    /api/v1.0/exercises/filters       distinct values (with counts) for each filter
    GET    /api/v1.0/exercises/top-rated     best average review stars (aggregation)
    GET    /api/v1.0/exercises/<id>          one exercise with its reviews
    PUT    /api/v1.0/exercises/<id>          update some fields  (admin, trainer)
    DELETE /api/v1.0/exercises/<id>          delete              (admin, trainer)
"""

import re

from flask import Blueprint

from decorators import role_required
from globals import exercises
from utils.constants import BODY_PARTS, EQUIPMENT, EXERCISE_LEVELS, EXERCISE_TYPES
from utils.errors import ApiError
from utils.pagination import PAGINATION_QUERY, facet_envelope, facet_page
from utils.responses import created, no_content, ok
from utils.validation import parse_object_id, validate_body, validate_query

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

# Filters that accept comma-separated values, e.g. ?body_part=Chest,Triceps
LIST_FILTERS = {"body_part": BODY_PARTS, "equipment": EQUIPMENT, "level": EXERCISE_LEVELS,
                "type": EXERCISE_TYPES}


def find_exercise(exercise_id, projection=None):
    """Shared with the reviews Blueprint."""
    exercise = exercises.find_one({"_id": parse_object_id(exercise_id, "exercise id")}, projection)
    if not exercise:
        raise ApiError(404, "Exercise not found")
    return exercise


def _title_taken(title, exclude_id=None):
    query = {"title": {"$regex": f"^{re.escape(title)}$", "$options": "i"}}
    if exclude_id:
        query["_id"] = {"$ne": exclude_id}
    return exercises.find_one(query, {"_id": 1}) is not None


@exercises_bp.route("/exercises", methods=["GET"])
def list_exercises():
    args = validate_query({
        **{name: {"type": "list", "items": {"type": "string", "choices": values}}
           for name, values in LIST_FILTERS.items()},
        "min_rating": {"type": "number", "min": 0, "max": 10},
        "q": {"type": "string", "max_len": 100},
        "sort": {"type": "string", "choices": ["rating", "title", "reviews"]},
        "order": {"type": "string", "choices": ["asc", "desc"]},
        **PAGINATION_QUERY,
    })

    match = {}
    if "q" in args:
        match["$text"] = {"$search": args["q"]}          # uses the text index on title + description
    for field in LIST_FILTERS:
        if field in args:
            match[field] = {"$in": args[field]}
    if "min_rating" in args:
        match["rating"] = {"$gte": args["min_rating"]}

    # Default order: best text match when searching, otherwise alphabetical
    sort_field = args.get("sort") or ("relevance" if "q" in args else "title")
    default_dir = "asc" if sort_field == "title" else "desc"
    direction = 1 if args.get("order", default_dir) == "asc" else -1
    sort = {
        "relevance": {"score": {"$meta": "textScore"}},
        "rating": {"rating": direction, "title": 1},
        "title": {"title": direction},
        "reviews": {"review_count": direction, "title": 1},
    }[sort_field]

    pipeline = [
        {"$match": match},
        {"$addFields": {"review_count": {"$size": "$reviews"},
                        "avg_stars": {"$round": [{"$avg": "$reviews.stars"}, 2]}}},
        {"$project": {"reviews": 0}},
        {"$sort": sort},
        facet_page(args["pn"], args["ps"]),
    ]
    # Case-insensitive ordering of titles ("bench" next to "Bench"). A $text search
    # cannot be combined with a collation, so it keeps the default.
    options = {} if "q" in args else {"collation": {"locale": "en", "strength": 2}}
    result = list(exercises.aggregate(pipeline, **options))
    return ok(facet_envelope(result, args["pn"], args["ps"]))


@exercises_bp.route("/exercises", methods=["POST"])
@role_required("admin", "trainer")
def create_exercise():
    data = validate_body(EXERCISE_SCHEMA)
    if _title_taken(data["title"]):
        raise ApiError(409, "An exercise with this title already exists")
    data.setdefault("description", None)
    data.setdefault("rating", None)
    data["reviews"] = []
    new_id = exercises.insert_one(data).inserted_id
    return created("Exercise created", new_id, "exercises.get_exercise", id=new_id)


@exercises_bp.route("/exercises/filters", methods=["GET"])
def exercise_filters():
    # One query: $facet runs a $sortByCount for each field in parallel
    pipeline = [{"$facet": {field: [{"$sortByCount": f"${field}"},
                                    {"$project": {"_id": 0, "value": "$_id", "count": 1}}]
                            for field in LIST_FILTERS}}]
    return ok(list(exercises.aggregate(pipeline))[0])


@exercises_bp.route("/exercises/top-rated", methods=["GET"])
def top_rated():
    args = validate_query({
        "body_part": {"type": "list", "items": {"type": "string", "choices": BODY_PARTS}},
        "min_reviews": {"type": "int", "min": 1, "max": 50, "default": 2},
        "limit": {"type": "int", "min": 1, "max": 50, "default": 10},
    })
    match = {"reviews.0": {"$exists": True}}         # at least one review
    if "body_part" in args:
        match["body_part"] = {"$in": args["body_part"]}
    pipeline = [
        {"$match": match},
        {"$project": {
            "title": 1, "body_part": 1, "equipment": 1, "level": 1, "type": 1,
            "review_count": {"$size": "$reviews"},
            "avg_stars": {"$avg": "$reviews.stars"},
        }},
        # Ignore exercises with too few reviews: one 5-star review is not "top rated"
        {"$match": {"review_count": {"$gte": args["min_reviews"]}}},
        {"$sort": {"avg_stars": -1, "review_count": -1, "title": 1}},
        {"$limit": args["limit"]},
        {"$set": {"avg_stars": {"$round": ["$avg_stars", 2]}}},
    ]
    results = list(exercises.aggregate(pipeline))
    return ok({"data": results, "count": len(results), "min_reviews": args["min_reviews"]})


@exercises_bp.route("/exercises/<id>", methods=["GET"])
def get_exercise(id):
    exercise = find_exercise(id)
    stars = [r["stars"] for r in exercise["reviews"]]
    exercise["review_count"] = len(stars)
    exercise["avg_stars"] = round(sum(stars) / len(stars), 2) if stars else None
    return ok(exercise)


@exercises_bp.route("/exercises/<id>", methods=["PUT"])
@role_required("admin", "trainer")
def update_exercise(id):
    exercise = find_exercise(id, {"_id": 1})
    data = validate_body(EXERCISE_SCHEMA, partial=True)
    if "title" in data and _title_taken(data["title"], exclude_id=exercise["_id"]):
        raise ApiError(409, "An exercise with this title already exists")
    exercises.update_one({"_id": exercise["_id"]}, {"$set": data})
    return ok({"message": "Exercise updated",
               "exercise": exercises.find_one({"_id": exercise["_id"]}, {"reviews": 0})})


@exercises_bp.route("/exercises/<id>", methods=["DELETE"])
@role_required("admin", "trainer")
def delete_exercise(id):
    exercise = find_exercise(id, {"_id": 1})
    exercises.delete_one({"_id": exercise["_id"]})
    # Workout logs keep their own copy of the title, so past workouts stay readable
    return no_content()
