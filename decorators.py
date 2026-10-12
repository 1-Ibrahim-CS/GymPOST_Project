"""
Authentication and authorisation decorators.

    @jwt_required             -> any logged-in user (valid, unexpired, not logged-out token)
    @role_required("admin")   -> logged in AND one of the listed roles

The decoded token is stored in flask.g.user so routes can read
g.user["user_id"], g.user["role"] and g.user["member_id"].
"""

from functools import wraps

import jwt
from bson import ObjectId
from flask import g, request

from globals import SECRET_KEY, blacklist
from utils.errors import ApiError


def jwt_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        token = request.headers.get("x-access-token")
        if not token:
            raise ApiError(401, "Token is missing",
                           {"x-access-token": "Log in at /api/v1.0/auth/login and send the token in this header"})
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise ApiError(401, "Token has expired", {"x-access-token": "Log in again to get a new token"})
        except jwt.InvalidTokenError:
            raise ApiError(401, "Token is invalid")
        if blacklist.find_one({"token": token}):
            raise ApiError(401, "Token has been logged out", {"x-access-token": "Log in again to get a new token"})
        g.user = payload
        g.token = token
        return func(*args, **kwargs)
    return wrapper


def role_required(*roles):
    """Allows the request only if the logged-in user has one of the given roles."""
    def decorator(func):
        @wraps(func)
        @jwt_required                    # role checks always need a valid token first
        def wrapper(*args, **kwargs):
            if g.user["role"] not in roles:
                raise ApiError(403, "You do not have permission to do this",
                               {"required_role": " or ".join(roles), "your_role": g.user["role"]})
            return func(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------- ownership helpers

def is_admin():
    return g.user["role"] == "admin"


def ensure_self_or_admin(member_id):
    """403 unless the caller is an admin or the member who owns this record."""
    if is_admin():
        return
    if g.user.get("member_id") != str(member_id):
        raise ApiError(403, "You can only access your own member record")


def current_member_id():
    """The caller's member ObjectId, or 403 for staff accounts that have no member record."""
    member_id = g.user.get("member_id")
    if not member_id:
        raise ApiError(403, "Only member accounts can do this",
                       {"your_role": g.user["role"]})
    return ObjectId(member_id)
