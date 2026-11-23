from functools import wraps

import jwt
from flask import g, jsonify, make_response, request

import globals


# any logged-in user - the decoded token is saved in g.user for the route to use
def jwt_required(func):
    @wraps(func)
    def jwt_required_wrapper(*args, **kwargs):
        token = request.headers.get("x-access-token")
        if not token:
            return make_response(jsonify({
                "error": "Token is missing",
                "details": {"x-access-token": "Log in at /api/v1.0/auth/login and send the token in this header"}
            }), 401)
        try:
            data = jwt.decode(token, globals.SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return make_response(jsonify({"error": "Token has expired"}), 401)
        except jwt.InvalidTokenError:
            return make_response(jsonify({"error": "Token is invalid"}), 401)

        if globals.db.blacklist.find_one({"token": token}) is not None:
            return make_response(jsonify({"error": "Token has been logged out"}), 401)

        g.user = data
        g.token = token
        return func(*args, **kwargs)
    return jwt_required_wrapper


# logged in AND one of the given roles, e.g. @role_required("admin", "trainer")
def role_required(*roles):
    def decorator(func):
        @wraps(func)
        @jwt_required
        def role_required_wrapper(*args, **kwargs):
            if g.user["role"] not in roles:
                return make_response(jsonify({
                    "error": "You do not have permission to do this",
                    "details": {"required_role": " or ".join(roles), "your_role": g.user["role"]}
                }), 403)
            return func(*args, **kwargs)
        return role_required_wrapper
    return decorator
