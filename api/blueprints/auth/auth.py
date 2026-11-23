from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from bson import ObjectId
from flask import Blueprint, g, jsonify, make_response, request

from blueprints.members.members import new_member_document
from decorators import jwt_required
import globals
from utils.validation import now_utc, validate_body

auth_bp = Blueprint("auth", __name__)


# REGISTER - creates the login account and its member record
@auth_bp.route("/api/v1.0/auth/register", methods=["POST"])
def register():
    data, errors = validate_body(globals.SCHEMAS["register"])
    if errors:
        return make_response(jsonify({"error": "Validation failed", "details": errors}), 400)
    data["username"] = data["username"].lower()

    # check both so the user sees every conflict at once
    conflicts = {}
    if globals.db.users.find_one({"username": data["username"]}) is not None:
        conflicts["username"] = "This username is already taken"
    if globals.db.users.find_one({"email": data["email"]}) is not None or \
            globals.db.members.find_one({"email": data["email"]}) is not None:
        conflicts["email"] = "An account with this email already exists"
    if conflicts:
        return make_response(jsonify({"error": "Account already exists", "details": conflicts}), 409)

    if globals.db.branches.find_one({"_id": data["home_branch_id"]}) is None:
        return make_response(jsonify({"error": "Validation failed",
                                      "details": {"home_branch_id": "No branch exists with this id"}}), 400)

    member_id = globals.db.members.insert_one(new_member_document(data)).inserted_id
    try:
        user_id = globals.db.users.insert_one({
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
        globals.db.members.delete_one({"_id": member_id})
        raise

    new_member_link = request.host_url + "api/v1.0/members/" + str(member_id)
    response = make_response(jsonify({"message": "Account created", "id": str(member_id),
                                    "url": new_member_link, "user_id": str(user_id)}), 201)
    response.headers["Location"] = new_member_link
    return response


# LOGIN - HTTP Basic auth, returns a JWT valid for 8 minutes
@auth_bp.route("/api/v1.0/auth/login", methods=["GET"])
def login():
    auth = request.authorization
    if not auth or not auth.username or not auth.password:
        return make_response(jsonify({
            "error": "Login details are missing",
            "details": {"authorization": "Send the username and password using HTTP Basic auth"}
        }), 401)

    user = globals.db.users.find_one({"username": auth.username.lower()})
    # same message for unknown user and wrong password so usernames can't be guessed
    if user is None or not bcrypt.checkpw(auth.password.encode(), bytes(user["password"])):
        return make_response(jsonify({"error": "Invalid username or password"}), 401)

    expires = datetime.now(timezone.utc) + timedelta(minutes=globals.TOKEN_EXPIRY_MINUTES)
    user_info = {
        "user_id": str(user["_id"]),
        "username": user["username"],
        "role": user["role"],
        "member_id": str(user["member_id"]) if user.get("member_id") else None
    }
    token = jwt.encode({**user_info, "exp": expires}, globals.SECRET_KEY, algorithm="HS256")
    return make_response(jsonify({"token": token, "expires_at": expires, "user": user_info}), 200)


# LOGOUT - the token is blacklisted until it would have expired anyway
@auth_bp.route("/api/v1.0/auth/logout", methods=["GET"])
@jwt_required
def logout():
    globals.db.blacklist.insert_one({
        "token": g.token,
        "expires_at": datetime.fromtimestamp(g.user["exp"], tz=timezone.utc),
        "logged_out_at": now_utc()
    })
    return make_response(jsonify({"message": "Logged out successfully"}), 200)


# CURRENT USER
@auth_bp.route("/api/v1.0/auth/me", methods=["GET"])
@jwt_required
def show_current_user():
    user = globals.db.users.find_one({"_id": ObjectId(g.user["user_id"])})
    if user is None:
        return make_response(jsonify({"error": "User account no longer exists"}), 404)
    user.pop("password", None)

    if user.get("member_id"):
        user["member"] = globals.db.members.find_one(
            {"_id": user["member_id"]},
            {"name": 1, "home_branch_id": 1, "membership": 1, "preferred_workout": 1, "experience_level": 1})
    return make_response(jsonify(user), 200)
