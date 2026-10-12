from datetime import timedelta

from utils.constants import EXPERIENCE_LEVELS, GENDERS, PLAN_DAYS, WORKOUT_TYPES
from utils.validation import now_utc

BODY_METRICS_SCHEMA = {
    "weight_kg": {"type": "number", "min": 30, "max": 300},
    "height_m": {"type": "number", "min": 1.0, "max": 2.5},
    "fat_percentage": {"type": "number", "min": 2, "max": 70},
    "resting_bpm": {"type": "int", "min": 30, "max": 120},
}

# member profile fields - used by /auth/register and the members routes
PROFILE_SCHEMA = {
    "name": {"type": "string", "min_len": 2, "max_len": 80},
    "gender": {"type": "string", "choices": GENDERS},
    "age": {"type": "int", "min": 16, "max": 100},
    "home_branch_id": {"type": "objectid"},
    "body_metrics": {"type": "object", "schema": BODY_METRICS_SCHEMA, "partial": True},
    "preferred_workout": {"type": "string", "choices": WORKOUT_TYPES},
    "experience_level": {"type": "string", "choices": EXPERIENCE_LEVELS},
    "workout_frequency": {"type": "int", "min": 0, "max": 7},
    "water_intake_l": {"type": "number", "min": 0, "max": 10},
}

REQUIRED_PROFILE_FIELDS = ["name", "gender", "age", "home_branch_id"]


def compute_bmi(weight_kg, height_m):
    if weight_kg is None or height_m is None:
        return None
    return round(weight_kg / (height_m ** 2), 1)


# a membership that starts today and lasts the plan's number of days
def new_membership(plan):
    start = now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
    return {"plan": plan, "start_date": start,
            "end_date": start + timedelta(days=PLAN_DAYS[plan]), "status": "active"}


# a member document with the same shape as the seeded ones
def new_member_document(data):
    metrics = data.get("body_metrics", {})
    weight = metrics.get("weight_kg")
    height = metrics.get("height_m")
    return {
        "name": data["name"],
        "email": data["email"],
        "gender": data["gender"],
        "age": data["age"],
        "home_branch_id": data["home_branch_id"],
        "body_metrics": {
            "weight_kg": weight,
            "height_m": height,
            "bmi": compute_bmi(weight, height),
            "fat_percentage": metrics.get("fat_percentage"),
            "resting_bpm": metrics.get("resting_bpm"),
        },
        "preferred_workout": data.get("preferred_workout"),
        "experience_level": data.get("experience_level", "Beginner"),
        "workout_frequency": data.get("workout_frequency"),
        "water_intake_l": data.get("water_intake_l"),
        "membership": new_membership(data.get("plan", "Monthly")),
        "workouts": [],
        "joined_at": now_utc(),
    }
