import re
from datetime import datetime, timezone

from bson import ObjectId
from flask import request

# Each route describes its input as a dict of field -> rules, for example
#     {"stars": {"type": "int", "required": True, "min": 1, "max": 5}}
# validate_body() / validate_query() return (cleaned_data, errors).
# errors is a dict of field -> message, so the route can send every problem back at once.
#
# rules: type (string, int, number, bool, email, objectid, datetime, list, object),
#        required, nullable, min, max, min_len, max_len, choices, pattern, pattern_msg,
#        items (rules for each list element), min_items, max_items,
#        schema (rules for a nested object), partial, default (query only)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# ?pn=<page number>&ps=<page size> - added to the query rules of every list route
PAGINATION_QUERY = {
    "pn": {"type": "int", "min": 1, "default": 1},
    "ps": {"type": "int", "min": 1, "max": 100, "default": 10},
}


class FieldError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def now_utc():
    return datetime.now(timezone.utc)


# accepts "2026-10-20" and "2026-10-20T18:00:00Z"
def parse_datetime(value):
    if not isinstance(value, str):
        raise ValueError
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"        # Python 3.10 fromisoformat does not accept Z
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def check_choices(value, rules):
    choices = rules.get("choices")
    if not choices:
        return value
    for choice in choices:
        # case-insensitive match, saved in the canonical case
        if isinstance(value, str) and isinstance(choice, str) and value.lower() == choice.lower():
            return choice
        if value == choice:
            return choice
    raise FieldError("Must be one of: " + ", ".join(map(str, choices)))


def check_range(value, rules):
    if "min" in rules and value < rules["min"]:
        raise FieldError("Must be at least " + str(rules["min"]))
    if "max" in rules and value > rules["max"]:
        raise FieldError("Must be at most " + str(rules["max"]))
    return value


# checks one value against its rules and returns the cleaned value
def check_value(value, rules):
    if value is None:
        if rules.get("nullable"):
            return None
        raise FieldError("Must not be null")

    kind = rules.get("type", "string")

    if kind == "string" or kind == "email":
        if not isinstance(value, str):
            raise FieldError("Must be a string")
        value = value.strip()
        min_len = rules.get("min_len", 1)
        if len(value) < min_len:
            if min_len == 1:
                raise FieldError("Must not be empty")
            raise FieldError("Must be at least " + str(min_len) + " characters")
        if "max_len" in rules and len(value) > rules["max_len"]:
            raise FieldError("Must be at most " + str(rules["max_len"]) + " characters")
        if kind == "email":
            if not EMAIL_RE.match(value):
                raise FieldError("Must be a valid email address")
            value = value.lower()
        if "pattern" in rules and not re.fullmatch(rules["pattern"], value):
            raise FieldError(rules.get("pattern_msg", "Has an invalid format"))
        return check_choices(value, rules)

    if kind == "int":
        # True is an int in Python, so bool has to be rejected first
        if isinstance(value, bool) or not isinstance(value, int):
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            else:
                raise FieldError("Must be a whole number")
        return check_choices(check_range(value, rules), rules)

    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FieldError("Must be a number")
        return check_range(float(value), rules)

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
        return check_range(value, rules)

    if kind == "list":
        if not isinstance(value, list):
            raise FieldError("Must be a list")
        if len(value) < rules.get("min_items", 0):
            raise FieldError("Must contain at least " + str(rules["min_items"]) + " item(s)")
        if "max_items" in rules and len(value) > rules["max_items"]:
            raise FieldError("Must contain at most " + str(rules["max_items"]) + " items")
        cleaned = []
        errors = {}
        for i, item in enumerate(value):
            try:
                cleaned.append(check_value(item, rules.get("items", {})))
            except FieldError as e:
                errors["[" + str(i) + "]"] = e.message
        if errors:
            raise FieldError(errors)
        return cleaned

    if kind == "object":
        if not isinstance(value, dict):
            raise FieldError("Must be an object")
        cleaned, errors = validate(value, rules["schema"], rules.get("partial", False))
        if errors:
            raise FieldError(errors)
        return cleaned

    raise ValueError("Unknown rule type " + kind)


# partial=True skips the "required" checks (used by PUT)
def validate(data, schema, partial):
    cleaned = {}
    errors = {}
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


# {"address": {"city": "Belfast"}} -> {"address.city": "Belfast"}
# so a PUT that changes one sub-field does not wipe out the others
def to_dotted(data, prefix=""):
    flat = {}
    for key, value in data.items():
        path = prefix + key
        if isinstance(value, dict) and value:
            flat.update(to_dotted(value, path + "."))
        else:
            flat[path] = value
    return flat


def validate_body(schema, partial=False):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}, {"body": "Send a JSON object with the header Content-Type: application/json"}
    cleaned, errors = validate(data, schema, partial)
    if partial and not cleaned and not errors:
        errors["body"] = "Provide at least one field to update"
    return cleaned, errors


# query string values are always text, so convert them before checking
def convert_query_value(raw, rules):
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
    if kind == "list":
        # comma-separated values: ?level=Beginner,Expert
        return [part.strip() for part in raw.split(",") if part.strip()]
    return raw


def validate_query(schema):
    cleaned = {}
    errors = {}
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
            cleaned[name] = check_value(convert_query_value(raw.strip(), rules), rules)
        except FieldError as e:
            errors[name] = e.message
    return cleaned, errors
