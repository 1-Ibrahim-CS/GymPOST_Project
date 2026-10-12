import os

from dotenv import load_dotenv
from pymongo import MongoClient

# read MONGODB_URI and SECRET_KEY from the .env file (seed.py uses the same file)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

MONGO_URI = os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017")
DB_NAME = os.environ.get("DB_NAME", "gymDB")
SECRET_KEY = os.environ.get("SECRET_KEY", "pulsefit-dev-secret-change-me")
TOKEN_EXPIRY_MINUTES = 30

# tz_aware=True so dates come back in UTC and can be compared with datetime.now(timezone.utc)
client = MongoClient(MONGO_URI, tz_aware=True)
db = client[DB_NAME]

users = db.users
members = db.members
exercises = db.exercises
branches = db.branches
classes = db.classes
blacklist = db.blacklist
