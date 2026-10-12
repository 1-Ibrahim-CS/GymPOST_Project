"""
Pagination helpers.

List endpoints accept ?pn=<page number>&ps=<page size> and return:
    {"data": [...], "pagination": {"page": 1, "page_size": 10, "total": 2909, "pages": 291}}
The total lets a front end draw page links without a second request.
"""

import math

# Merge into any query schema that supports paging
PAGINATION_QUERY = {
    "pn": {"type": "int", "min": 1, "default": 1},
    "ps": {"type": "int", "min": 1, "max": 100, "default": 10},
}


def page_envelope(data, total, pn, ps):
    return {
        "data": data,
        "pagination": {"page": pn, "page_size": ps, "total": total,
                       "pages": math.ceil(total / ps) if total else 0},
    }


def paginate_find(collection, query, pn, ps, projection=None, sort=None):
    """Runs a find() for one page and counts the full result set."""
    cursor = collection.find(query, projection)
    if sort:
        cursor = cursor.sort(sort)
    data = list(cursor.skip((pn - 1) * ps).limit(ps))
    return page_envelope(data, collection.count_documents(query), pn, ps)


def facet_page(pn, ps):
    """Aggregation stage that returns one page and the total count in a single query."""
    return {"$facet": {
        "data": [{"$skip": (pn - 1) * ps}, {"$limit": ps}],
        "total": [{"$count": "count"}],
    }}


def facet_envelope(result, pn, ps):
    """Converts the output of facet_page() into the standard envelope."""
    doc = result[0] if result else {"data": [], "total": []}
    total = doc["total"][0]["count"] if doc["total"] else 0
    return page_envelope(doc["data"], total, pn, ps)
