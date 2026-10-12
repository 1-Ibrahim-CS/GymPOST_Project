"""
globals.py - shared configuration and the MongoDB connection.

Settings come from environment variables (or the project .env file) so that no
secrets live in the code. The same MONGODB_URI variable is used by seed.py, so the
API always talks to the database that was seeded.
"""

import os

from dotenv import load_dotenv
from pymongo import MongoClient

# Load KEY=value pairs from the .env next to this file. Variables already set in the
# environment take priority, so `MONGODB_URI=... python app.py` overrides the file.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

MONGO_URI = os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017")
DB_NAME = os.environ.get("DB_NAME", "gymDB")
SECRET_KEY = os.environ.get("SECRET_KEY", "pulsefit-dev-secret-change-me")
TOKEN_EXPIRY_MINUTES = 30

# tz_aware=True makes pymongo return timezone-aware UTC datetimes, so they can be
# compared safely with datetime.now(timezone.utc) anywhere in the code.
client = MongoClient(MONGO_URI, tz_aware=True)
db = client[DB_NAME]

users = db.users
members = db.members
exercises = db.exercises
branches = db.branches
classes = db.classes
blacklist = db.blacklist
