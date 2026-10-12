from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from bson import ObjectId
from flask import Blueprint, g, jsonify, make_response, request

from decorators import jwt_required
from globals import SECRET_KEY, TOKEN_EXPIRY_MINUTES, blacklist, branches, members, users
from utils.constants import PLAN_DAYS
from utils.membership import PROFILE_SCHEMA, REQUIRED_PROFILE_FIELDS, new_member_document
from utils.validation import now_utc, validate_body

auth_bp = Blueprint("auth", __name__)

# account fields + the member profile fields
REGISTER_SCHEMA = {
    "username": {"type": "string", "required": True, "min_len": 3, "max_len": 30,
                 "pattern": r"[A-Za-z0-9._-]+",
                 "pattern_msg": "Use only letters, numbers, dots, underscores and hyphens"},
    "email": {"type": "email", "required": True, "max_len": 120},
    # bcrypt only uses the first 72 bytes of a password
    "password": {"type": "string", "required": True, "min_len": 8, "max_len": 72},
    "plan": {"type": "string", "choices": list(PLAN_DAYS)},
}
for field_name, field_rules in PROFILE_SCHEMA.items():
    REGISTER_SCHEMA[field_name] = {**field_rules, "required": field_name in REQUIRED_PROFILE_FIELDS}


# REGISTER - creates the login account and its member record
@auth_bp.route("/api/v1.0/auth/register", methods=["POST"])
def register():
    data, errors = validate_body(REGISTER_SCHEMA)
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)
    data["username"] = data["username"].lower()

    # check both so the user sees every conflict at once
    conflicts = {}
    if users.find_one({"username": data["username"]}) is not None:
        conflicts["username"] = "This username is already taken"
    if users.find_one({"email": data["email"]}) is not None or \
            members.find_one({"email": data["email"]}) is not None:
        conflicts["email"] = "An account with this email already exists"
    if conflicts:
        return make_response(jsonify({"error": "Account already exists", "details": conflicts}), 409)

    if branches.find_one({"_id": data["home_branch_id"]}) is None:
        return make_response(jsonify({"error": "Validation failed",
                                      "details": {"home_branch_id": "No branch exists with this id"}}), 400)

    member_id = members.insert_one(new_member_document(data)).inserted_id
    try:
        user_id = users.insert_one({
            "username": data["username"],
            "email": data["email"],
            "name": data["name"],
            "password": bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt()),
            "role": "member",
            "member_id": member_id,
            "created_at": now_utc()
        }).inserted_id
    except Exception:
        # remove the member again if the account could not be saved
        members.delete_one({"_id": member_id})
        raise

    new_member_link = request.host_url + "api/v1.0/members/" + str(member_id)
    response = make_response(jsonify({"message": "Account created", "id": str(member_id),
                                    "url": new_member_link, "user_id": str(user_id)}), 201)
    response.headers["Location"] = new_member_link
    return response


# LOGIN - HTTP Basic auth, returns a JWT valid for 30 minutes
@auth_bp.route("/api/v1.0/auth/login", methods=["POST"])
def login():
    auth = request.authorization
    if not auth or not auth.username or not auth.password:
        return make_response(jsonify({
            "error": "Login details are missing",
            "details": {"authorization": "Send the username and password using HTTP Basic auth"}
        }), 401)

    user = users.find_one({"username": auth.username.lower()})
    # same message for unknown user and wrong password so usernames can't be guessed
    if user is None or not bcrypt.checkpw(auth.password.encode(), bytes(user["password"])):
        return make_response(jsonify({"error": "Invalid username or password"}), 401)

    expires = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRY_MINUTES)
    user_info = {
        "user_id": str(user["_id"]),
        "username": user["username"],
        "role": user["role"],
        "member_id": str(user["member_id"]) if user.get("member_id") else None
    }
    token = jwt.encode({**user_info, "exp": expires}, SECRET_KEY, algorithm="HS256")
    return make_response(jsonify({"token": token, "expires_at": expires, "user": user_info}), 200)


# LOGOUT - the token is blacklisted until it would have expired anyway
@auth_bp.route("/api/v1.0/auth/logout", methods=["GET"])
@jwt_required
def logout():
    blacklist.insert_one({
        "token": g.token,
        "expires_at": datetime.fromtimestamp(g.user["exp"], tz=timezone.utc),
        "logged_out_at": now_utc()
    })
    return make_response(jsonify({"message": "Logged out successfully"}), 200)


# CURRENT USER
@auth_bp.route("/api/v1.0/auth/me", methods=["GET"])
@jwt_required
def show_current_user():
    user = users.find_one({"_id": ObjectId(g.user["user_id"])})
    if user is None:
        return make_response(jsonify({"error": "User account no longer exists"}), 404)
    user.pop("password", None)

    if user.get("member_id"):
        user["member"] = members.find_one(
            {"_id": user["member_id"]},
            {"name": 1, "home_branch_id": 1, "membership": 1, "preferred_workout": 1, "experience_level": 1})
    return make_response(jsonify(user), 200)
