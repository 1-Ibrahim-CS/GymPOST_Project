"""
seed.py - builds the MongoDB database for the Gym and Fitness Class Booking System.

Sources (Kaggle):
  megaGymDataset.csv                  -> exercises collection
  gym_members_exercise_tracking.csv   -> members collection (one row = one member)

Generated (documented in the Design and Development document):
  branches, trainers (users with role "trainer"), classes with embedded bookings,
  member names/emails/memberships, workout history, exercise reviews,
  the options document (the allowed values the API validates against) and
  the schemas document (the validation rules for every request body).

Usage:
  python seed.py                 # insert straight into MongoDB (needs pymongo + bcrypt)
  python seed.py --json-only     # only write mongoimport-ready JSON files to ./seed_output

Every random choice uses a fixed seed, so the script always produces the same data.
"""

import argparse
import csv
import json
import os
import random
import secrets
from datetime import datetime, timedelta, timezone

random.seed(661)

EXERCISES_CSV = "megaGymDataset.csv"
MEMBERS_CSV = "gym_members_exercise_tracking.csv"
DB_NAME = "gymDB"
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")


def load_env(path=ENV_FILE):
    """Reads KEY=value lines from the project .env so the connection string stays out of git."""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()
MONGO_URI = os.environ.get("MONGODB_URI")
DEFAULT_PASSWORD = "Password123!"      # every seeded account uses this password
TODAY = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)  # schedule is built around the day you run it
HISTORY_WEEKS = 8                      # weeks of past workouts
CLASS_HISTORY_WEEKS = 4                # weeks of past classes
FUTURE_WEEKS = 4                       # weeks of upcoming classes
MAX_MEMBERS = 100                      # first 100 rows of the members CSV
MAX_EXERCISES = 300                    # spread across every type and body part


# ---------------------------------------------------------------- helpers

class Oid:
    """Stand-in for a MongoDB ObjectId so the build step needs no extra libraries."""
    def __init__(self):
        self.hex = format(int(datetime.now(timezone.utc).timestamp()), "08x") + secrets.token_hex(8)


def new_id():
    return Oid()


def rnd_dt(start, end):
    return start + timedelta(seconds=random.randint(0, int((end - start).total_seconds())))


FIRST_M = ["James", "Jack", "Conor", "Ryan", "Daniel", "Adam", "Ethan", "Liam", "Noah", "Oliver",
           "Matthew", "Aaron", "Sean", "Callum", "Harry", "Thomas", "Ali", "Omar", "Hassan", "Arjun",
           "Lucas", "Mark", "Paul", "Niall", "Ciaran", "Patrick", "Owen", "Rory", "Samuel", "David"]
FIRST_F = ["Emma", "Sophie", "Grace", "Aoife", "Chloe", "Ella", "Lucy", "Olivia", "Amelia", "Erin",
           "Hannah", "Niamh", "Sarah", "Katie", "Ava", "Mia", "Zara", "Fatima", "Aisha", "Priya",
           "Rachel", "Laura", "Megan", "Ciara", "Orla", "Isla", "Ruby", "Holly", "Anna", "Leah"]
LAST = ["Murphy", "Kelly", "O'Neill", "Smith", "Wilson", "Campbell", "Stewart", "Thompson", "Doherty",
        "Quinn", "McLaughlin", "Robinson", "Johnston", "Moore", "Brown", "Martin", "Walsh", "Byrne",
        "Khan", "Ahmed", "Patel", "Hughes", "Gallagher", "Kennedy", "Reid", "Graham", "Bell", "Scott",
        "Hamilton", "Boyle", "Fitzpatrick", "McCann", "Burns", "Ferguson", "Watson", "Clarke"]

used_emails = set()


def make_person(gender=None):
    gender = gender or random.choice(["Male", "Female"])
    first = random.choice(FIRST_M if gender == "Male" else FIRST_F)
    last = random.choice(LAST)
    base = f"{first}.{last}".lower().replace("'", "")
    email, n = f"{base}@example.com", 1
    while email in used_emails:
        n += 1
        email = f"{base}{n}@example.com"
    used_emails.add(email)
    return f"{first} {last}", email, email.split("@")[0]


# ---------------------------------------------------------------- branches

# Real coordinates (approximate centre of each area). GeoJSON uses [longitude, latitude].
BRANCHES = [
    ("Belfast City Centre", "Belfast", "BT1", -5.9301, 54.5973),
    ("Titanic Quarter", "Belfast", "BT3", -5.9093, 54.6082),
    ("Queen's Quarter", "Belfast", "BT7", -5.9342, 54.5844),
    ("Lisburn", "Lisburn", "BT28", -6.0580, 54.5162),
    ("Bangor", "Bangor", "BT20", -5.6680, 54.6600),
    ("Derry~Londonderry", "Derry~Londonderry", "BT48", -7.3086, 54.9966),
]
FACILITIES = ["Free weights", "Cardio zone", "Spin studio", "Yoga studio", "Sauna", "Swimming pool",
              "Lockers", "Parking", "Cafe", "Functional training rig", "Showers"]


def build_branches():
    out = []
    for name, city, postcode, lng, lat in BRANCHES:
        out.append({
            "_id": new_id(),
            "name": f"PulseFit {name}",
            "address": {"area": name, "city": city, "postcode": postcode},
            "location": {"type": "Point", "coordinates": [lng, lat]},
            "opening_hours": {"weekdays": "06:00-22:00", "weekends": "08:00-20:00"},
            "facilities": sorted(random.sample(FACILITIES, random.randint(5, 9))),
            "capacity": random.choice([120, 150, 180, 200]),
            "phone": f"028 90{random.randint(100000, 999999)}",
            "created_at": TODAY - timedelta(days=random.randint(400, 1500)),
        })
    return out


# ---------------------------------------------------------------- exercises

def clean_rating(value):
    """The source uses blank and 0.0 for 'not rated'; both become null."""
    try:
        r = float(value)
    except (TypeError, ValueError):
        return None
    return r if r > 0 else None


def build_exercises():
    out, seen = [], set()
    with open(EXERCISES_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            title = row["Title"].strip()
            if title.lower() in seen:          # 9 duplicate titles in the source
                continue
            seen.add(title.lower())
            desc = row["Desc"].strip() or None
            out.append({
                "_id": new_id(),
                "title": title,
                "description": desc,
                "type": row["Type"].strip(),
                "body_part": row["BodyPart"].strip(),
                "equipment": row["Equipment"].strip() or "Other",
                "level": row["Level"].strip(),
                "rating": clean_rating(row["Rating"]),
                "reviews": [],
            })
    return out


def trim_exercises(all_exercises):
    # keep MAX_EXERCISES: take one from each type + body part group in turn,
    # rated exercises first, so every filter value is still in the data
    groups = {}
    for e in all_exercises:
        groups.setdefault((e["type"], e["body_part"]), []).append(e)
    for g in groups.values():
        g.sort(key=lambda e: e["rating"] is None)
    picked = []
    while len(picked) < MAX_EXERCISES and any(groups.values()):
        for key in sorted(groups):
            if groups[key] and len(picked) < MAX_EXERCISES:
                picked.append(groups[key].pop(0))
    return picked


# ---------------------------------------------------------------- trainers + admin accounts

CLASS_TYPES = {
    # workout type from the members dataset -> class titles, duration (min), level
    "Yoga": [("Vinyasa Flow", 60), ("Yin Yoga", 60), ("Power Yoga", 45), ("Pilates Core", 45)],
    "HIIT": [("HIIT Blast", 30), ("Tabata", 30), ("Bootcamp", 45), ("Circuit Training", 45)],
    "Cardio": [("Spin", 45), ("Rhythm Ride", 45), ("Cardio Kickboxing", 45), ("Step Aerobics", 45)],
    "Strength": [("Body Pump", 60), ("Kettlebell Strength", 45), ("Powerlifting Basics", 60),
                 ("Functional Strength", 45)],
}


def build_staff(branches):
    users, trainers = [], []
    name, email, username = "Site Admin", "admin@pulsefit.example.com", "admin"
    users.append({"_id": new_id(), "username": username, "email": email, "name": name,
                  "role": "admin", "created_at": TODAY - timedelta(days=500)})
    for b in branches:
        for _ in range(3):
            name, email, username = make_person()
            specialities = random.sample(list(CLASS_TYPES), 2)
            t = {"_id": new_id(), "username": username, "email": email, "name": name,
                 "role": "trainer", "branch_id": b["_id"], "specialities": specialities,
                 "created_at": TODAY - timedelta(days=random.randint(60, 900))}
            users.append(t)
            trainers.append(t)
    return users, trainers


# ---------------------------------------------------------------- members + workouts

PLANS = [("Monthly", 30, 0.55), ("Quarterly", 90, 0.25), ("Annual", 365, 0.15), ("Student", 120, 0.05)]
LEVEL = {"1": "Beginner", "2": "Intermediate", "3": "Expert"}
GENDERS = ["Male", "Female"]


def pick_plan():
    r, acc = random.random(), 0
    for name, days, p in PLANS:
        acc += p
        if r <= acc:
            return name, days
    return PLANS[0][:2]


def jitter(value, pct, lo=None, hi=None, nd=1):
    v = value * random.uniform(1 - pct, 1 + pct)
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return round(v, nd)


def build_workouts(row, exercises_by_body):
    """Generate HISTORY_WEEKS of workouts around this member's own averages."""
    freq = int(row["Workout_Frequency (days/week)"])
    dur = float(row["Session_Duration (hours)"]) * 60
    cal = float(row["Calories_Burned"])
    avg_bpm = int(row["Avg_BPM"])
    max_bpm = int(row["Max_BPM"])
    main_type = row["Workout_Type"]
    workouts = []
    start = TODAY - timedelta(weeks=HISTORY_WEEKS)
    for week in range(HISTORY_WEEKS):
        days = sorted(random.sample(range(7), min(7, max(1, freq + random.choice([-1, 0, 0, 0, 1])))))
        for d in days:
            wtype = main_type if random.random() < 0.7 else random.choice(list(CLASS_TYPES))
            minutes = jitter(dur, 0.15, 20, 150, 0)
            w = {
                "_id": new_id(),
                "date": start + timedelta(weeks=week, days=d, hours=random.randint(6, 20)),
                "workout_type": wtype,
                "duration_min": int(minutes),
                "calories_burned": int(cal * minutes / dur * random.uniform(0.9, 1.1)),
                "avg_bpm": int(jitter(avg_bpm, 0.05, 90, max_bpm, 0)),
                "max_bpm": int(jitter(max_bpm, 0.03, avg_bpm + 5, 205, 0)),
                "exercises": [],
            }
            if wtype in ("Strength", "HIIT"):
                for body in random.sample(list(exercises_by_body), random.randint(3, 5)):
                    ex = random.choice(exercises_by_body[body])
                    w["exercises"].append({
                        "exercise_id": ex["_id"], "title": ex["title"],
                        "sets": random.randint(2, 5), "reps": random.choice([6, 8, 10, 12, 15]),
                        "weight_kg": None if ex["equipment"] == "Body Only"
                        else random.choice([5, 7.5, 10, 12.5, 15, 20, 25, 30, 40, 50, 60, 80]),
                    })
            workouts.append(w)
    return workouts


def build_members(branches, exercises):
    strength = [e for e in exercises if e["type"] in ("Strength", "Powerlifting", "Plyometrics")]
    exercises_by_body = {}
    for e in strength:
        exercises_by_body.setdefault(e["body_part"], []).append(e)
    exercises_by_body = {k: v for k, v in exercises_by_body.items() if len(v) >= 5}

    members, users = [], []
    with open(MEMBERS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if len(members) >= MAX_MEMBERS:
                break
            name, email, username = make_person(row["Gender"])
            plan, days = pick_plan()
            if random.random() < 0.8:      # 80% active: current period covers today
                end = TODAY + timedelta(days=random.randint(1, days))
            else:                          # 20% lapsed in the last two months
                end = TODAY - timedelta(days=random.randint(1, 60))
            start = end - timedelta(days=days)
            joined = min(start, TODAY - timedelta(days=random.randint(60, 900)))
            m = {
                "_id": new_id(),
                "name": name,
                "email": email,
                "gender": row["Gender"],
                "age": int(row["Age"]),
                "home_branch_id": random.choice(branches)["_id"],
                "body_metrics": {
                    "weight_kg": float(row["Weight (kg)"]),
                    "height_m": float(row["Height (m)"]),
                    "bmi": float(row["BMI"]),
                    "fat_percentage": float(row["Fat_Percentage"]),
                    "resting_bpm": int(row["Resting_BPM"]),
                },
                "preferred_workout": row["Workout_Type"],
                "experience_level": LEVEL[row["Experience_Level"]],
                "workout_frequency": int(row["Workout_Frequency (days/week)"]),
                "water_intake_l": float(row["Water_Intake (liters)"]),
                "membership": {
                    "plan": plan, "start_date": start, "end_date": end,
                    "status": "active" if end >= TODAY else "expired",
                },
                "workouts": [w for w in build_workouts(row, exercises_by_body) if w["date"] <= end],
                "joined_at": joined,
            }
            members.append(m)
            users.append({"_id": new_id(), "username": username, "email": email, "name": name,
                          "role": "member", "member_id": m["_id"], "created_at": start})
    return members, users


# ---------------------------------------------------------------- classes + bookings

SLOTS = [(0, 18), (1, 12), (2, 7), (3, 18), (5, 10)]      # (weekday, hour): 5 classes a week per branch
CLASS_LEVELS = ["Beginner", "All levels", "Intermediate", "Advanced"]


def build_classes(branches, trainers, members):
    by_branch = {}
    for m in members:
        by_branch.setdefault(m["home_branch_id"].hex, []).append(m)
    trainers_by_branch = {}
    for t in trainers:
        trainers_by_branch.setdefault(t["branch_id"].hex, []).append(t)

    classes = []
    first_monday = TODAY - timedelta(days=TODAY.weekday(), weeks=CLASS_HISTORY_WEEKS)
    for b in branches:
        local_members = by_branch.get(b["_id"].hex, [])
        timetable = []                                     # same weekly timetable every week
        for day, hour in SLOTS:
            trainer = random.choice(trainers_by_branch[b["_id"].hex])
            ctype = random.choice(trainer["specialities"])
            title, minutes = random.choice(CLASS_TYPES[ctype])
            timetable.append((day, hour, trainer, ctype, title, minutes,
                              random.choice([12, 15, 20, 25]),
                              random.choice(CLASS_LEVELS)))
        for week in range(CLASS_HISTORY_WEEKS + FUTURE_WEEKS):
            for day, hour, trainer, ctype, title, minutes, capacity, level in timetable:
                start = first_monday + timedelta(weeks=week, days=day, hours=hour)
                past = start < TODAY
                # members who like this workout type are more likely to book
                pool = [m for m in local_members if m["preferred_workout"] == ctype] * 3 + local_members
                demand = random.uniform(0.45, 1.05) if past else random.uniform(0.1, 0.8)
                wanted = min(capacity, int(capacity * demand))
                chosen, seen = [], set()
                random.shuffle(pool)
                for m in pool:
                    if len(chosen) >= wanted:
                        break
                    if m["membership"]["end_date"] < start:      # lapsed members can't book
                        continue
                    if m["_id"].hex not in seen:
                        seen.add(m["_id"].hex)
                        chosen.append(m)
                bookings = []
                for m in chosen:
                    cancelled = random.random() < 0.08
                    bookings.append({
                        "_id": new_id(),
                        "member_id": m["_id"],
                        "member_name": m["name"],
                        "booked_at": start - timedelta(days=random.randint(0, 10), hours=random.randint(1, 20)),
                        "status": "cancelled" if cancelled else "booked",
                        "attended": (None if not past or cancelled else random.random() < 0.85),
                    })
                active = sum(1 for bk in bookings if bk["status"] == "booked")
                classes.append({
                    "_id": new_id(),
                    "title": title,
                    "category": ctype,
                    "description": f"{title} is a {minutes}-minute {ctype.lower()} class for {level.lower()} members.",
                    "branch_id": b["_id"],
                    "branch_name": b["name"],
                    "trainer_id": trainer["_id"],
                    "trainer_name": trainer["name"],
                    "start_time": start,
                    "duration_min": minutes,
                    "level": level,
                    "capacity": capacity,
                    "booked_count": active,
                    "status": "completed" if past else "scheduled",
                    "bookings": bookings,
                })
    return classes


# ---------------------------------------------------------------- reviews

REVIEW_TEXT = {
    5: ["Brilliant exercise, really feel it working.", "One of my favourites, great results.",
        "Easy to follow and very effective."],
    4: ["Good exercise, took a few tries to get the form right.", "Solid movement, would recommend.",
        "Works well as part of a circuit."],
    3: ["Decent but nothing special.", "Okay, a bit awkward with the equipment.",
        "Fine, but I prefer other variations."],
    2: ["Hard to get the form right.", "Not very comfortable for me."],
    1: ["Hurt my wrists, would not do again."],
}


def add_reviews(exercises, members):
    for ex in random.sample(exercises, int(len(exercises) * 0.35)):
        for m in random.sample(members, random.randint(1, 4)):
            stars = random.choices([5, 4, 3, 2, 1], weights=[35, 35, 18, 8, 4])[0]
            ex["reviews"].append({
                "_id": new_id(),
                "member_id": m["_id"],
                "member_name": m["name"],
                "stars": stars,
                "comment": random.choice(REVIEW_TEXT[stars]),
                "created_at": rnd_dt(TODAY - timedelta(days=300), TODAY),
            })


# ---------------------------------------------------------------- options

def build_options(all_exercises):
    # one document with every allowed value the API checks input against.
    # Exercise values come from the full cleaned CSV, so every value in the dataset is accepted.
    return {
        "_id": "options",
        "plan_days": {name: days for name, days, share in PLANS},
        "membership_statuses": ["active", "expired"],
        "genders": GENDERS,
        "experience_levels": list(LEVEL.values()),
        "workout_types": sorted(CLASS_TYPES),
        "class_levels": CLASS_LEVELS,
        "class_statuses": ["scheduled", "completed", "cancelled"],
        "booking_statuses": ["booked", "cancelled"],
        "exercise_types": sorted({e["type"] for e in all_exercises}),
        "body_parts": sorted({e["body_part"] for e in all_exercises}),
        "equipment": sorted({e["equipment"] for e in all_exercises}),
        "exercise_levels": sorted({e["level"] for e in all_exercises}),
        "roles": ["admin", "trainer", "member"],
    }


# ---------------------------------------------------------------- schemas

def build_schemas(options):
    # the validation rules for every request body, one entry per route that reads a body.
    # rules: type, required, nullable, min, max, min_len, max_len, choices, pattern, pattern_msg,
    #        items, min_items, max_items, schema (nested object), partial
    plans = list(options["plan_days"])

    body_metrics = {
        "weight_kg": {"type": "number", "min": 30, "max": 300},
        "height_m": {"type": "number", "min": 1.0, "max": 2.5},
        "fat_percentage": {"type": "number", "min": 2, "max": 70},
        "resting_bpm": {"type": "int", "min": 30, "max": 120},
    }
    # member profile fields - used by register and the members routes
    profile = {
        "name": {"type": "string", "min_len": 2, "max_len": 80},
        "gender": {"type": "string", "choices": options["genders"]},
        "age": {"type": "int", "min": 16, "max": 100},
        "home_branch_id": {"type": "objectid"},
        "body_metrics": {"type": "object", "schema": body_metrics, "partial": True},
        "preferred_workout": {"type": "string", "choices": options["workout_types"]},
        "experience_level": {"type": "string", "choices": options["experience_levels"]},
        "workout_frequency": {"type": "int", "min": 0, "max": 7},
        "water_intake_l": {"type": "number", "min": 0, "max": 10},
    }
    required_profile = ["name", "gender", "age", "home_branch_id"]
    profile_with_required = {name: {**rules, "required": name in required_profile} for name, rules in profile.items()}
    email = {"type": "email", "required": True, "max_len": 120}

    hours = {"type": "string", "required": True,
             "pattern": r"([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d",
             "pattern_msg": "Use the format HH:MM-HH:MM, e.g. 06:00-22:00"}
    branch = {
        "name": {"type": "string", "required": True, "min_len": 3, "max_len": 80},
        "address": {"type": "object", "required": True, "schema": {
            "area": {"type": "string", "required": True, "max_len": 80},
            "city": {"type": "string", "required": True, "max_len": 80},
            "postcode": {"type": "string", "required": True, "max_len": 8,
                         "pattern": r"[A-Za-z]{1,2}\d[A-Za-z\d]?(\s?\d[A-Za-z]{2})?",
                         "pattern_msg": "Must be a UK postcode or postcode district, e.g. BT1 or BT1 5GS"},
        }},
        "lat": {"type": "number", "required": True, "min": -90, "max": 90},
        "lng": {"type": "number", "required": True, "min": -180, "max": 180},
        "opening_hours": {"type": "object", "required": True, "schema": {"weekdays": hours, "weekends": hours}},
        "facilities": {"type": "list", "max_items": 30, "items": {"type": "string", "max_len": 50}},
        "capacity": {"type": "int", "required": True, "min": 1, "max": 1000},
        "phone": {"type": "string", "required": True, "pattern": r"[0-9 +()-]{7,20}",
                  "pattern_msg": "Must be 7-20 digits, spaces or + ( ) -"},
    }

    gym_class = {
        "title": {"type": "string", "required": True, "min_len": 3, "max_len": 80},
        "category": {"type": "string", "required": True, "choices": options["workout_types"]},
        "description": {"type": "string", "max_len": 500},
        "branch_id": {"type": "objectid", "required": True},
        "trainer_id": {"type": "objectid"},            # a trainer creating a class teaches it themself
        "start_time": {"type": "datetime", "required": True},
        "duration_min": {"type": "int", "required": True, "min": 1, "max": 300},
        "level": {"type": "string", "required": True, "choices": options["class_levels"]},
        "capacity": {"type": "int", "required": True, "min": 1, "max": 100},
    }

    exercise_entry = {
        "exercise_id": {"type": "objectid", "required": True},
        "sets": {"type": "int", "required": True, "min": 1, "max": 20},
        "reps": {"type": "int", "required": True, "min": 1, "max": 100},
        "weight_kg": {"type": "number", "nullable": True, "min": 0, "max": 500},
    }

    return {
        "_id": "schemas",
        # POST /auth/register - account fields + the member profile
        "register": {
            "username": {"type": "string", "required": True, "min_len": 3, "max_len": 30,
                         "pattern": r"[A-Za-z0-9._-]+",
                         "pattern_msg": "Use only letters, numbers, dots, underscores and hyphens"},
            "email": email,
            # bcrypt only uses the first 72 bytes of a password
            "password": {"type": "string", "required": True, "min_len": 8, "max_len": 72},
            "plan": {"type": "string", "choices": plans},
            **profile_with_required,
        },
        # POST /members - admins add a member at the front desk without a login account
        "member_create": {"email": email, "plan": {"type": "string", "choices": plans}, **profile_with_required},
        # PUT /members/<id> - members edit their own profile, admins can also change the email
        "member_update": profile,
        "member_admin_update": {"email": email, **profile},
        # PUT /members/<id>/membership
        "membership": {"plan": {"type": "string", "required": True, "choices": plans}},
        # POST and PUT /branches - on PUT the address and opening hours can be sent in part
        "branch_create": branch,
        "branch_update": {**branch,
                          "address": {**branch["address"], "partial": True},
                          "opening_hours": {**branch["opening_hours"], "partial": True}},
        # POST and PUT /classes - a class can't move branch, but its status can be changed on PUT
        "class_create": gym_class,
        "class_update": {**{name: rules for name, rules in gym_class.items() if name != "branch_id"},
                         "status": {"type": "string", "choices": options["class_statuses"]}},
        # PUT /classes/<id>/bookings/<booking_id>/attendance
        "attendance": {"attended": {"type": "bool", "required": True}},
        # POST and PUT /exercises
        "exercise": {
            "title": {"type": "string", "required": True, "min_len": 3, "max_len": 120},
            "description": {"type": "string", "nullable": True, "max_len": 2000},
            "type": {"type": "string", "required": True, "choices": options["exercise_types"]},
            "body_part": {"type": "string", "required": True, "choices": options["body_parts"]},
            "equipment": {"type": "string", "required": True, "choices": options["equipment"]},
            "level": {"type": "string", "required": True, "choices": options["exercise_levels"]},
            "rating": {"type": "number", "nullable": True, "min": 0, "max": 10},
        },
        # POST and PUT /exercises/<id>/reviews
        "review": {
            "stars": {"type": "int", "required": True, "min": 1, "max": 5},
            "comment": {"type": "string", "required": True, "min_len": 2, "max_len": 500},
        },
        # POST and PUT /members/<id>/workouts
        "workout": {
            "date": {"type": "datetime", "required": True},
            "workout_type": {"type": "string", "required": True, "choices": options["workout_types"]},
            "duration_min": {"type": "int", "required": True, "min": 1, "max": 300},
            "calories_burned": {"type": "int", "required": True, "min": 0, "max": 5000},
            "avg_bpm": {"type": "int", "required": True, "min": 40, "max": 220},
            "max_bpm": {"type": "int", "required": True, "min": 40, "max": 230},
            "exercises": {"type": "list", "max_items": 30,
                          "items": {"type": "object", "schema": exercise_entry}},
        },
    }


# ---------------------------------------------------------------- output

def to_extended_json(obj):
    """Converts Oid/datetime into MongoDB Extended JSON for mongoimport."""
    if isinstance(obj, Oid):
        return {"$oid": obj.hex}
    if isinstance(obj, datetime):
        return {"$date": obj.strftime("%Y-%m-%dT%H:%M:%SZ")}
    if isinstance(obj, dict):
        return {k: to_extended_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_extended_json(v) for v in obj]
    return obj


def to_bson(obj):
    from bson import ObjectId
    if isinstance(obj, Oid):
        return ObjectId(obj.hex)
    if isinstance(obj, dict):
        return {k: to_bson(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_bson(v) for v in obj]
    return obj


def write_json(collections, folder="seed_output"):
    try:
        import bcrypt
        hashed = bcrypt.hashpw(DEFAULT_PASSWORD.encode(), bcrypt.gensalt()).decode()
        for u in collections["users"]:
            u["password"] = hashed
    except ImportError:
        print("  bcrypt not installed: users.json has no passwords (pip install bcrypt to add them)")
    os.makedirs(folder, exist_ok=True)
    for name, docs in collections.items():
        path = os.path.join(folder, f"{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([to_extended_json(d) for d in docs], f, ensure_ascii=False)
        print(f"  wrote {path} ({len(docs)} documents)")


def insert_mongo(collections):
    import bcrypt
    from pymongo import MongoClient, ASCENDING, TEXT, GEOSPHERE

    if not MONGO_URI:
        raise SystemExit("MONGODB_URI is not set: add it to the .env file in the project root")

    # One hash for all seeded accounts keeps seeding fast; real sign-ups hash individually.
    hashed = bcrypt.hashpw(DEFAULT_PASSWORD.encode(), bcrypt.gensalt())
    for u in collections["users"]:
        u["password"] = hashed

    db = MongoClient(MONGO_URI)[DB_NAME]
    for name, docs in collections.items():
        db[name].drop()
        db[name].insert_many([to_bson(d) for d in docs])
        print(f"  {name}: {len(docs)} documents")
    db.blacklist.drop()

    db.branches.create_index([("location", GEOSPHERE)])
    db.exercises.create_index([("title", TEXT), ("description", TEXT)])
    db.exercises.create_index([("body_part", ASCENDING), ("equipment", ASCENDING), ("level", ASCENDING)])
    db.members.create_index("email", unique=True)
    db.users.create_index("username", unique=True)
    db.users.create_index("email", unique=True)
    db.classes.create_index([("branch_id", ASCENDING), ("start_time", ASCENDING)])
    db.classes.create_index("bookings.member_id")
    db.blacklist.create_index("token", unique=True)
    print("  indexes created")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-only", action="store_true",
                        help="write JSON files instead of inserting into MongoDB")
    args = parser.parse_args()

    print("Building data...")
    branches = build_branches()
    all_exercises = build_exercises()
    exercises = trim_exercises(all_exercises)
    options = build_options(all_exercises)
    staff, trainers = build_staff(branches)
    members, member_users = build_members(branches, exercises)
    classes = build_classes(branches, trainers, members)
    add_reviews(exercises, members)

    collections = {
        "branches": branches,
        "exercises": exercises,
        "members": members,
        "classes": classes,
        "users": staff + member_users,
        "options": [options],
        "schemas": [build_schemas(options)],
    }
    if args.json_only:
        write_json(collections)
    else:
        insert_mongo(collections)
    print(f"Done. Every seeded account's password is: {DEFAULT_PASSWORD}")


if __name__ == "__main__":
    main()