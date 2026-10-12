"""
Request validation.

Each endpoint describes its input as a schema: a dict of field name -> rules.

    REVIEW_SCHEMA = {
        "stars":   {"type": "int", "required": True, "min": 1, "max": 5},
        "comment": {"type": "string", "max_len": 500},
    }

validate_body(schema) checks the JSON body and validate_query(schema) checks the
query string. Both collect every problem before failing, reject unknown fields and
raise ApiError(400) with a "details" dict of field -> message.

Supported rule keys:
    type       string | int | number | bool | email | objectid | datetime | list | object
    required   field must be present (ignored for partial updates)
    nullable   null is accepted
    min / max  numeric range (inclusive)
    min_len / max_len   string length (min_len defaults to 1, so "" is rejected)
    choices    allowed values (matched case-insensitively, stored in canonical case)
    pattern    regular expression a string must match (pattern_msg explains it)
    items      rules for each element of a list; min_items / max_items for its length
    schema     nested schema for an object
    default    query parameters only: value used when the parameter is missing
"""

import re
from datetime import datetime, timezone

from bson import ObjectId
from flask import request

from utils.errors import ApiError

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class FieldError(Exception):
    """One field failed validation. message is a string, or a dict for nested fields."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


# ------------------------------------------------------------------ single values

def now_utc():
    return datetime.now(timezone.utc)


def parse_datetime(value):
    """Accepts ISO 8601 dates ("2026-10-20") and date-times ("2026-10-20T18:00:00Z")."""
    if not isinstance(value, str):
        raise ValueError
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"        # Python 3.10's fromisoformat does not accept Z
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:                  # no offset given: treat as UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_object_id(value, label="id"):
    """Turns a URL segment or field into an ObjectId, or raises 400 with a clear message."""
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ApiError(400, f"Invalid {label}", {label: "Must be a 24-character hexadecimal ObjectId"})


def _check_choices(value, rules):
    choices = rules.get("choices")
    if not choices:
        return value
    for choice in choices:
        if isinstance(value, str) and isinstance(choice, str) and value.lower() == choice.lower():
            return choice
        if value == choice:
            return choice
    raise FieldError(f"Must be one of: {', '.join(map(str, choices))}")


def _check_range(value, rules):
    if "min" in rules and value < rules["min"]:
        raise FieldError(f"Must be at least {rules['min']}")
    if "max" in rules and value > rules["max"]:
        raise FieldError(f"Must be at most {rules['max']}")
    return value


def check_value(value, rules):
    """Validates one value against its rules and returns the cleaned value."""
    if value is None:
        if rules.get("nullable"):
            return None
        raise FieldError("Must not be null")

    kind = rules.get("type", "string")

    if kind in ("string", "email"):
        if not isinstance(value, str):
            raise FieldError("Must be a string")
        value = value.strip()
        if len(value) < rules.get("min_len", 1):
            raise FieldError("Must not be empty" if rules.get("min_len", 1) == 1
                             else f"Must be at least {rules['min_len']} characters")
        if "max_len" in rules and len(value) > rules["max_len"]:
            raise FieldError(f"Must be at most {rules['max_len']} characters")
        if kind == "email":
            if not EMAIL_RE.match(value):
                raise FieldError("Must be a valid email address")
            value = value.lower()
        if "pattern" in rules and not re.fullmatch(rules["pattern"], value):
            raise FieldError(rules.get("pattern_msg", "Has an invalid format"))
        return _check_choices(value, rules)

    if kind == "int":
        # bool is a subclass of int in Python, so True would otherwise pass as 1
        if isinstance(value, bool) or not isinstance(value, int):
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            else:
                raise FieldError("Must be a whole number")
        return _check_choices(_check_range(value, rules), rules)

    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FieldError("Must be a number")
        return _check_range(float(value), rules)

    if kind == "bool":
        if not isinstance(value, bool):
            raise FieldError("Must be true or false")
        return value

    if kind == "objectid":
        if not isinstance(value, str) or not ObjectId.is_valid(value):
            raise FieldError("Must be a 24-character hexadecimal ObjectId")
        return ObjectId(value)

    if kind == "datetime":
        try:
            value = parse_datetime(value)
        except (ValueError, TypeError):
            raise FieldError("Must be an ISO 8601 date, e.g. 2026-10-20 or 2026-10-20T18:00:00Z")
        return _check_range(value, rules)

    if kind == "list":
        if not isinstance(value, list):
            raise FieldError("Must be a list")
        if len(value) < rules.get("min_items", 0):
            raise FieldError(f"Must contain at least {rules['min_items']} item(s)")
        if "max_items" in rules and len(value) > rules["max_items"]:
            raise FieldError(f"Must contain at most {rules['max_items']} items")
        cleaned, errors = [], {}
        for i, item in enumerate(value):
            try:
                cleaned.append(check_value(item, rules.get("items", {})))
            except FieldError as e:
                errors[f"[{i}]"] = e.message
        if errors:
            raise FieldError(errors)
        return cleaned

    if kind == "object":
        if not isinstance(value, dict):
            raise FieldError("Must be an object")
        cleaned, errors = _validate(value, rules["schema"], rules.get("partial", False))
        if errors:
            raise FieldError(errors)
        return cleaned

    raise ValueError(f"Unknown rule type {kind}")      # programming error, not user error


def _validate(data, schema, partial):
    """Returns (cleaned_data, errors). partial=True skips 'required' checks (updates)."""
    cleaned, errors = {}, {}
    for key in data:
        if key not in schema:
            errors[key] = "Unknown field"
    for name, rules in schema.items():
        if name not in data:
            if rules.get("required") and not partial:
                errors[name] = "This field is required"
            continue
        try:
            cleaned[name] = check_value(data[name], rules)
        except FieldError as e:
            errors[name] = e.message
    return cleaned, errors


def to_dotted(data, prefix=""):
    """Flattens nested objects into MongoDB dot notation for partial $set updates.

    {"address": {"city": "Belfast"}} -> {"address.city": "Belfast"}
    so updating one sub-field does not wipe out the other sub-fields.
    """
    flat = {}
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            flat.update(to_dotted(value, path + "."))
        else:
            flat[path] = value
    return flat


# ------------------------------------------------------------------ request helpers

def get_json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "Request body must be a JSON object",
                       {"body": "Send a JSON object with the header Content-Type: application/json"})
    return data


def validate_body(schema, partial=False):
    """Validates the JSON body. partial=True is used by PUT routes that update some fields."""
    data = get_json_body()
    cleaned, errors = _validate(data, schema, partial)
    if partial and not cleaned and not errors:
        errors["body"] = "Provide at least one field to update"
    if errors:
        raise ApiError(400, "Validation failed", errors)
    return cleaned


def _convert_query_value(raw, rules):
    """Query string values are always text; convert them before the normal checks."""
    kind = rules.get("type", "string")
    if kind == "int":
        try:
            return int(raw)
        except ValueError:
            raise FieldError("Must be a whole number")
    if kind == "number":
        try:
            return float(raw)
        except ValueError:
            raise FieldError("Must be a number")
    if kind == "bool":
        if raw.lower() in ("true", "1", "yes"):
            return True
        if raw.lower() in ("false", "0", "no"):
            return False
        raise FieldError("Must be true or false")
    if kind == "list":                        # comma-separated values: ?level=Beginner,Expert
        return [part.strip() for part in raw.split(",") if part.strip()]
    return raw


def validate_query(schema):
    """Validates request.args against a schema and fills in defaults."""
    cleaned, errors = {}, {}
    for key in request.args:
        if key not in schema:
            errors[key] = "Unknown query parameter"
    for name, rules in schema.items():
        raw = request.args.get(name)
        if raw is None or raw.strip() == "":
            if rules.get("required"):
                errors[name] = "This query parameter is required"
            elif "default" in rules:
                cleaned[name] = rules["default"]
            continue
        try:
            cleaned[name] = check_value(_convert_query_value(raw.strip(), rules), rules)
        except FieldError as e:
            errors[name] = e.message
    if errors:
        raise ApiError(400, "Invalid query parameters", errors)
    return cleaned
