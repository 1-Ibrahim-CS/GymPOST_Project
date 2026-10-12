"""
auth Blueprint - registration, login (JWT), logout (token blacklist) and the current user.

    POST /api/v1.0/auth/register   create a user account and its linked member record
    POST /api/v1.0/auth/login      HTTP Basic auth -> JWT valid for 30 minutes
    GET  /api/v1.0/auth/logout     blacklist the current token
    GET  /api/v1.0/auth/me         the logged-in user's account (and member summary)
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from bson import ObjectId
from flask import Blueprint, g, request

from decorators import jwt_required
from globals import SECRET_KEY, TOKEN_EXPIRY_MINUTES, blacklist, branches, members, users
from utils.constants import PLAN_DAYS
from utils.errors import ApiError
from utils.membership import PROFILE_SCHEMA, REQUIRED_PROFILE_FIELDS, new_member_document
from utils.responses import created, ok
from utils.validation import now_utc, validate_body

auth_bp = Blueprint("auth", __name__)

# Registration = account fields + the member profile fields (required ones marked here)
REGISTER_SCHEMA = {
    "username": {"type": "string", "required": True, "min_len": 3, "max_len": 30,
                 "pattern": r"[A-Za-z0-9._-]+",
                 "pattern_msg": "Use only letters, numbers, dots, underscores and hyphens"},
    "email": {"type": "email", "required": True, "max_len": 120},
    # bcrypt only uses the first 72 bytes of a password, so longer ones are rejected
    "password": {"type": "string", "required": True, "min_len": 8, "max_len": 72},
    "plan": {"type": "string", "choices": list(PLAN_DAYS)},
    **{name: {**rules, "required": name in REQUIRED_PROFILE_FIELDS}
       for name, rules in PROFILE_SCHEMA.items()},
}


def _public_user(user):
    """A user document without the password hash."""
    user = dict(user)
    user.pop("password", None)
    return user


@auth_bp.route("/auth/register", methods=["POST"])
def register():
    data = validate_body(REGISTER_SCHEMA)
    data["username"] = data["username"].lower()

    # Check every conflict first so the user sees all of them at once
    conflicts = {}
    if users.find_one({"username": data["username"]}):
        conflicts["username"] = "This username is already taken"
    if users.find_one({"email": data["email"]}) or members.find_one({"email": data["email"]}):
        conflicts["email"] = "An account with this email already exists"
    if conflicts:
        raise ApiError(409, "Account already exists", conflicts)
    if not branches.find_one({"_id": data["home_branch_id"]}, {"_id": 1}):
        raise ApiError(400, "Validation failed", {"home_branch_id": "No branch exists with this id"})

    member_id = members.insert_one(new_member_document(data)).inserted_id
    try:
        user_id = users.insert_one({
            "username": data["username"],
            "email": data["email"],
            "name": data["name"],
            "password": bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt()),
            "role": "member",
            "member_id": member_id,
            "created_at": now_utc(),
        }).inserted_id
    except Exception:
        # Two writes without a transaction: undo the first if the second fails
        members.delete_one({"_id": member_id})
        raise

    # The new member record is the useful resource to link to; the user id is returned too
    return created("Account created", member_id, "members.get_member",
                   extra={"user_id": str(user_id)}, id=member_id)


@auth_bp.route("/auth/login", methods=["POST"])
def login():
    auth = request.authorization
    if not auth or not auth.username or not auth.password:
        raise ApiError(401, "Login details are missing",
                       {"authorization": "Send the username and password using HTTP Basic auth"})

    user = users.find_one({"username": auth.username.lower()})
    # Same message for unknown user and wrong password, so usernames can't be probed
    if not user or not bcrypt.checkpw(auth.password.encode(), bytes(user["password"])):
        raise ApiError(401, "Invalid username or password")

    expires = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRY_MINUTES)
    payload = {
        "user_id": str(user["_id"]),
        "username": user["username"],
        "role": user["role"],
        "member_id": str(user["member_id"]) if user.get("member_id") else None,
        "exp": expires,
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
    return ok({
        "token": token,
        "expires_at": expires,
        "user": {k: v for k, v in payload.items() if k != "exp"},
    })


@auth_bp.route("/auth/logout", methods=["GET"])
@jwt_required
def logout():
    # Store the token until it would have expired anyway; a TTL index on expires_at
    # (created in app.py) lets MongoDB delete old entries automatically.
    blacklist.insert_one({
        "token": g.token,
        "expires_at": datetime.fromtimestamp(g.user["exp"], tz=timezone.utc),
        "logged_out_at": now_utc(),
    })
    return ok({"message": "Logged out successfully"})


@auth_bp.route("/auth/me", methods=["GET"])
@jwt_required
def me():
    user = users.find_one({"_id": ObjectId(g.user["user_id"])})
    if not user:
        raise ApiError(404, "User account no longer exists")
    body = _public_user(user)
    if user.get("member_id"):
        body["member"] = members.find_one(
            {"_id": user["member_id"]},
            {"name": 1, "home_branch_id": 1, "membership": 1, "preferred_workout": 1,
             "experience_level": 1})
    return ok(body)
