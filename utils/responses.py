"""Small helpers for success responses so every route answers in the same shape."""

from flask import jsonify, make_response, url_for


def created(message, new_id, endpoint, extra=None, **url_args):
    """201 Created with the new id, the URL of the new resource and a Location header.

    endpoint and url_args are passed to url_for, e.g.
        created("Review added", review_id, "reviews.get_review", id=ex_id, review_id=review_id)
    extra is an optional dict of additional fields for the response body.
    """
    url = url_for(endpoint, _external=True, **{k: str(v) for k, v in url_args.items()})
    body = {"message": message, "id": str(new_id), "url": url, **(extra or {})}
    response = make_response(jsonify(body), 201)
    response.headers["Location"] = url
    return response


def ok(body):
    return make_response(jsonify(body), 200)


def no_content():
    return make_response("", 204)
