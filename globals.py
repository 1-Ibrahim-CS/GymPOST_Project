import os

from dotenv import load_dotenv
from pymongo import MongoClient

# read MONGODB_URI and SECRET_KEY from the .env file (seed.py uses the same file)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

MONGO_URI = os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017")
DB_NAME = os.environ.get("DB_NAME", "gymDB")
SECRET_KEY = os.environ.get("SECRET_KEY", "pulsefit-dev-secret-change-me")
TOKEN_EXPIRY_MINUTES = 8

# tz_aware=True so dates come back in UTC and can be compared with datetime.now(timezone.utc)
# the blueprints use the collections through db, e.g. globals.db.classes.find_one(...)
# collections: users, members, exercises, branches, classes, blacklist, options, schemas
client = MongoClient(MONGO_URI, tz_aware=True)
db = client[DB_NAME]

# seed.py puts these in the database; they are read once when the app starts
# OPTIONS - allowed values for the enum fields (plans, genders, workout types, body parts ...)
# SCHEMAS - validation rules for every request body, e.g. globals.SCHEMAS["branch_create"]
OPTIONS = db.options.find_one({"_id": "options"})
SCHEMAS = db.schemas.find_one({"_id": "schemas"})
if OPTIONS is None or SCHEMAS is None:
    raise SystemExit("The options or schemas collection is empty - run Raw_Dataset/seed.py first")
