# Design Notes: PulseFit Gym API

These notes are source material for the Design and Development document. They cover:
1. Architecture
2. The data structures and why each was chosen
3. Indexes
4. The key algorithms, with the alternatives considered
5. How the dataset was cleaned and extended by `seed.py`
6. Validation, errors and status codes
7. Differences from the Biz Directory example
8. Testing evidence
9. Known limitations
10. Use of AI

## 1. Architecture

```
HTTP request
   │
   ▼
Flask app (app.py) ── CORS, MongoJSONProvider, JSON error handlers
   │
   ├─ Blueprint per resource (blueprints/<resource>/<resource>.py), all under /api/v1.0
   │     auth · branches · exercises · reviews · members · workouts · classes · bookings · reports
   │
   ├─ decorators.py        @jwt_required, @role_required(*roles)
   ├─ utils/validation.py  declarative schemas → (cleaned data, errors)
   └─ globals.py           one MongoClient (tz_aware) shared by every request
   │
   ▼
MongoDB gymDB: branches, exercises, members, classes, users, blacklist
```

**Why there are four Blueprints for sub-documents.** Reviews, workouts and bookings each have their own Blueprint, separate from their parent resource. Each file maps to one REST resource. Every route does its own id check, lookup and ownership check inline, so each route can be read from top to bottom without jumping to helpers.

**How routes return responses.** Every route builds its own response with `make_response(jsonify(...), status)`, for success and for errors. Errors use the shape `{"error": "<message>", "details": {...}}`. `validate_body()` and `validate_query()` return `(data, errors)`, and the route returns a 400 with `errors` as the details. The error handlers in `app.py` give 404, 405, other HTTP errors, duplicate keys and unexpected exceptions the same JSON shape.

**JSON serialisation.** A custom Flask JSON provider converts `ObjectId` to a string and `datetime` to ISO 8601 UTC for every response, so routes return pymongo documents directly. Alternatives:
- **Convert each document by hand** (`str(doc["_id"])`) as the Biz Directory does. It's easy to forget for nested ids.
- **`bson.json_util`.** It produces Extended JSON (`{"$oid": ...}`), which is awkward for front ends.

## 2. Data structures: embed or reference?

The general rule:
- **Embed** data that is always read with its parent, is owned by the parent and has a limited size.
- **Reference** data that has its own life, is shared, or would grow without limit.

| Collection | Embedded | Referenced | Reasoning |
|---|---|---|---|
| **branches** | `address`, `opening_hours`, `facilities[]`, `location` (GeoJSON) | none | Small fixed sub-objects that are always shown with the branch. `location` must be a GeoJSON Point in the document for the 2dsphere index. |
| **exercises** | `reviews[]` | `reviews.member_id` → members | A review only makes sense with its exercise, and is always shown with it. The number per exercise is small (0–4 seeded, and one per member is enforced). Embedding gives the average with no join. `member_name` is copied in so a review can be displayed without a lookup. |
| **members** | `body_metrics`, `membership`, `workouts[]` (each with `exercises[]`) | `home_branch_id` → branches; `workouts.exercises.exercise_id` → exercises | A member's workout history is private to them and read as a whole for stats. Embedding lets one aggregation produce all the statistics. The exercise `title` is copied into each entry so old workouts stay readable if an exercise is renamed or deleted. |
| **classes** | `bookings[]` | `branch_id`, `trainer_id`, `bookings.member_id` | Bookings belong to one class and their number is limited by `capacity` (≤ 100). Embedding is what makes the **atomic booking** possible: the capacity check and the booking live in the same document, and single-document updates are atomic. `branch_name` and `trainer_name` are copied in so the timetable needs no joins. |
| **users** | `specialities[]` (trainers) | `member_id` → members; `branch_id` → branches | Login data (password hash, role) is kept apart from the member profile. Staff accounts have no member record, and admins can create member records without logins. |
| **blacklist** | none | none | One document per logged-out token, with a TTL index. |

### Copies of data and how they are kept correct

Copying data (denormalisation) speeds up reads. The cost is that each copy must be updated when the original changes. Every case is handled:

| Copied field | Where the copy lives | Kept in step by |
|---|---|---|
| `branch_name` | classes | `PUT /branches/<id>` runs `classes.update_many({"branch_id": id}, {"$set": {"branch_name": ...}})` |
| `member_name` | classes.bookings, exercises.reviews | `PUT /members/<id>` uses `update_many` with **`array_filters`** (`bookings.$[b].member_name` where `b.member_id == id`), so only that member's elements change |
| `name` and `email` | users | `PUT /members/<id>` updates the linked user |
| `trainer_name` | classes | Set whenever the trainer of a class changes |
| exercise `title` | members.workouts.exercises | Deliberately not updated. It is a historical record of what was done. |

### Alternatives considered

- **Separate `bookings`, `reviews` and `workouts` collections.** This is the relational design. It would need `$lookup` for most reads.
  - Bookings would need a multi-document transaction, or a separate counter, to stop overbooking.
  - A unique compound index `(class_id, member_id)` would make duplicate bookings impossible.

  This was rejected because embedding gives atomicity without transactions and needs fewer queries. The trade-off is the document size limit, below.
- **Document size limit (16 MB).** Bookings are capped by capacity and reviews by one per member, so neither can grow without limit. Workouts can: about 24 per member are seeded on average (46 at most; a member document is about 6.5 KB). At about 200 bytes each, 16 MB is about 80,000 workouts, more than a lifetime of training. If it ever became a problem, the **bucket pattern** would help: a `workout_buckets` collection with one document per member per month.
- **Storing `status` versus computing it.** `membership.status` and class `status` are stored (as the seed creates them) but go stale as time passes. Every query that matters therefore works the status out from dates:
  - "active" means `membership.end_date >= now`
  - a class is bookable when `start_time > now`
  - reports treat a class as "happened" when `start_time <= now`

  An alternative would be a scheduled job that updates statuses every night.

## 3. Indexes

| Index | Created by | Used by |
|---|---|---|
| `branches.location` 2dsphere | seed.py | `$geoNear` in `/branches/near` (required) |
| `exercises` text index on `title` and `description` | seed.py | `q` full-text search, relevance sort (`$meta: "textScore"`) |
| `exercises (body_part, equipment, level)` | seed.py | Exercise filters |
| `members.email`, `users.username`, `users.email` unique | seed.py | Duplicate checks. Also a safety net: a race that slips past the application check becomes a 409 via the `DuplicateKeyError` handler. |
| `classes (branch_id, start_time)` | seed.py | Branch timetable and class listing |
| `classes.bookings.member_id` (multikey) | seed.py | `/members/<id>/bookings`, member rename and delete |
| `blacklist.token` unique | seed.py | Token check on every authenticated request |
| `blacklist.expires_at` TTL (`expireAfterSeconds: 0`) | app.py `ensure_indexes()` | MongoDB deletes each blacklisted token once it would have expired anyway, so the collection never grows |

## 4. Key algorithms

### 4.1 Atomic class booking (`blueprints/bookings/bookings.py`)

**The problem.** The naive approach reads the class, checks `booked_count < capacity`, then pushes the booking. Two requests can both read "1 place left" before either writes, and the class is overbooked. This is a race condition, also called check-then-act.

**The solution.** Every rule is part of the *filter* of a single `update_one`:

```python
classes.update_one(
    {"_id": class_id,
     "status": "scheduled",
     "start_time": {"$gt": now},
     "$expr": {"$lt": ["$booked_count", "$capacity"]},          # compares two fields
     "bookings": {"$not": {"$elemMatch": {"member_id": me, "status": "booked"}}}},
    {"$push": {"bookings": booking}, "$inc": {"booked_count": 1}})
```

MongoDB guarantees that the filter and the update on one document happen atomically. If any rule fails, the filter matches nothing and `modified_count == 0`. Only then does the code read the class again, purely to choose the right error:

| Failed rule | Response |
|---|---|
| Class cancelled | 400 |
| Class already started or taken place | 400 |
| Member already booked | 409 |
| Class full | 409 |

**Evidence.** 20 members were sent at a 3-place class at the same moment with a thread pool. Result: exactly 3 × 201 and 17 × 409, with `booked_count` 3 and 3 bookings stored.

**Related atomic updates:**
- **Cancel a booking.** The filter is `bookings: {$elemMatch: {_id, status: "booked"}}`, plus "scheduled" and "not started". The update is `$set bookings.$.status` and `$inc booked_count -1`, so the counter can never drift from the bookings.
- **Cancel a class.** A single update sets the class status, every active booking's status (`bookings.$[b].status` with `array_filters: [{"b.status": "booked"}]`) and `booked_count: 0`.
- **One review per member.** `{"reviews.member_id": {"$ne": me}}` in the filter of the `$push`.

**Alternatives:**
- **Multi-document transactions.** These need a replica set and are slower. They are unnecessary when everything is in one document.
- **Optimistic locking.** Add a `version` field, read it, then update with `{version: v}` in the filter and retry on failure. This works, but is more code and needs retries.
- **A separate bookings collection.** A unique `(class_id, member_id)` index stops duplicates, but capacity would still need a counter document updated atomically.

The extra checks before the update (membership active, membership covering the class date) don't depend on the class state, so they are safe to do first.

### 4.2 Trainer timetable clash (`blueprints/classes/classes.py`)

Two time ranges overlap when `existingStart < newEnd AND existingEnd > newStart`. The class end time isn't stored, so it is calculated in the query:

```python
{"start_time": {"$lt": new_end},
 "$expr": {"$gt": [{"$add": ["$start_time", {"$multiply": ["$duration_min", 60000]}]}, new_start]}}
```

`$add` of a date and milliseconds gives a date. Back-to-back classes (one ends exactly when the next starts) are allowed because the comparison is strict. Alternative: store `end_time` on every class. That makes queries simpler, but it is extra data to keep in sync.

### 4.3 Aggregation pipelines

| Endpoint | Pipeline idea |
|---|---|
| `GET /exercises` | `$match` (filters / `$text`) → `$addFields` `review_count` (`$size`) and `avg_stars` (`$avg` over `reviews.stars`) → `$project` drops the reviews array → `$sort` → **`$facet`** returning the page and the total count in one query. Titles are sorted case-insensitively using a collation (`$text` searches can't use a collation, so they sort by relevance). |
| `GET /exercises/filters` | One `$facet` with a `$sortByCount` per filter field. |
| `GET /exercises/top-rated` | `$project` `avg_stars` and `review_count` → `$match review_count >= min_reviews`, so one 5-star review isn't "top rated" → sort → limit. |
| `GET /members/<id>/stats` | `$unwind workouts` → `$replaceRoot` (work with workout fields directly) → `$match` date window → `$facet` into: **totals** (`$group` sum/avg/max/min), **weekly** (`$dateTrunc` to the Monday of each week), **by_type** (favourite = most sessions) and **top_exercises** (second `$unwind`, `$multiply` sets × reps). One round trip. |
| `GET /members/<id>/workouts` | `$unwind` + `$replaceRoot` + `$match` filters on the embedded array, then `$facet` paging. |
| `GET /members/<id>/bookings` | Runs over **classes**: `$match bookings.member_id` (indexed) → `$unwind bookings` → `$match` again to keep only this member's elements → reshape with the class details. |
| `/reports/popular-classes` | `$project` computes `attended` with **`$filter`** + `$size` over the bookings array, and `past_booked` with `$cond`. Then `$facet` groups by `{category, title}` and by category. Rates are calculated with a `$cond` that guards against dividing by zero. |
| `/reports/branch-usage` | Starts from **branches** and uses two **`$lookup`s with `let` + sub-pipelines**. Each sub-pipeline groups inside the lookup, so only one summary document per branch is joined, not every member and class. `$first` unwraps the result. |
| `/reports/peak-times` | `$unwind bookings` → `$dayOfWeek` / `$hour` → `$group`. `$addToSet` + `$size` counts distinct classes per slot. `$arrayElemAt` maps 1–7 to day names. |
| `/reports/trainer-performance` | `$group` by trainer with `$cond` sums for past/upcoming classes, then `$lookup` (localField + pipeline) to the users and branches collections. |
| `/reports/membership-summary` | `$facet`: status worked out with `$cond` on `end_date`; plan breakdown; expiring list with **`$dateDiff`** for `days_left`, and a separate count. |

**Alternatives:**
- **Load documents into Python and loop.** This is simpler to read, but moves all the data over the network and is much slower. The database does grouping best.
- **Pre-computed counters** (e.g. `avg_stars` stored on each exercise). Reads are faster, but every write must update the counter.
- **Materialised views with `$merge`.** Run the report pipelines on a schedule and store the results. This is good when reports are expensive and don't need to be live.

### 4.4 Geospatial search (`/branches/near`)

`$geoNear` must be the first stage of a pipeline and uses the 2dsphere index. It takes a GeoJSON point. Coordinates are ordered **[longitude, latitude]**: a common bug, which is why the API accepts `lat` and `lng` as separate named fields. It returns results nearest first with a `distanceField` in metres, which is converted to km with `$divide` and `$round`.

Alternatives:
- **`$near`** in `find()`. This also sorts by distance, but does not return the distance.
- **`$geoWithin` with `$centerSphere`.** This filters by radius but does not sort or give the distance.
- **Haversine calculation in Python.** This works for 6 branches but does not scale and ignores the index.

### 4.5 Search and filtering

- **Comma-separated values become `$in`.** For example `?level=Beginner,Expert` gives `{"level": {"$in": [...]}}`. Each value is checked against the enum, and matching is case-insensitive (the canonical value is stored).
- **Full-text search** uses the text index, which handles word stemming and ranks by relevance. An alternative is a `$regex` search: it gives exact substring matches but can't use a normal index and has no ranking. `$regex` is used for short fields such as branch name, member name and email, always with `re.escape()` so user input can't inject regex patterns. A further alternative is Atlas Search (Lucene) for fuzzy matching.
- **Unique names (branches, exercises) are compared case-insensitively.**

### 4.6 Pagination

The API uses `skip` / `limit` with `pn` and `ps`, and returns `total` and `pages` so a front end can draw page links. For `find()` the total comes from `count_documents`. For aggregations a single **`$facet`** returns the page and the count together.

Alternative: **range-based (cursor/keyset) pagination**, such as `?after=<last _id>`. This is faster on very large collections because `skip` still walks over the skipped documents, but it can't jump to page N. For collections of a few thousand documents, `skip` / `limit` is simpler and fine.

### 4.7 Authentication and authorisation

**Passwords.** Hashed with **bcrypt** (salted, deliberately slow). Login returns the same 401 message for an unknown user and a wrong password, so usernames can't be discovered. Passwords are limited to 8–72 characters, because bcrypt ignores everything after byte 72.

**Tokens.** A **JWT (HS256)** with the payload `user_id`, `username`, `role`, `member_id` and `exp` (30 minutes). The server keeps no session, and every protected request checks:
1. The token is present.
2. The signature is valid.
3. It has not expired.
4. It is not blacklisted.

The decoded token goes into `flask.g.user`.

**Logout.** JWTs can't be "deleted", so logout stores the token in `blacklist` with its expiry time. A **TTL index** removes the entry once the token would have expired anyway.

**Roles.** `@role_required("admin", "trainer")` wraps `@jwt_required`, so a role check always implies a valid token (401 first, then 403).

**Ownership** is checked in code, not by role:
- members may only access their own record, workouts, bookings and reviews
- trainers may only manage the classes they teach

The ownership check runs **before** the database lookup, so a member probing other ids always gets 403 and learns nothing about which ids exist.

Alternatives:
- **Server-side sessions** (e.g. Redis). Easy to revoke, but not stateless.
- **Short-lived access tokens plus refresh tokens.** No blacklist needed, but more complex.
- **Flask-JWT-Extended.** Ready-made decorators. The hand-written version was chosen so the mechanism is visible and can be explained.

### 4.8 Validation (`utils/validation.py`)

Each endpoint declares a schema, for example:

```python
{"stars": {"type": "int", "required": True, "min": 1, "max": 5}}
```

One function enforces:
- type, including rejecting `true` where an `int` is expected (in Python `bool` is a subclass of `int`)
- required fields
- min/max ranges and string lengths
- enum choices (case-insensitive)
- regex patterns (postcode, phone, opening hours)
- email format, ObjectId format and ISO 8601 dates
- nested objects and lists
- **unknown fields**, which are rejected

All errors are collected and returned together in `details`, nested to match the input, e.g. `{"exercises": {"[0]": {"sets": "Must be at least 1"}}}`.

The same rules validate query strings after converting the text values. `PUT` uses `partial=True`: nothing is required, but at least one field must be sent. Rules that involve several fields or the current time run after the schema, for example:
- `max_bpm >= avg_bpm`, checked against the stored values when updating
- no workouts in the future
- class start time in the future
- capacity not below `booked_count`

Partial updates of nested objects are turned into dot notation (`address.city`) by `to_dotted()`, so updating one sub-field does not wipe out the others.

Alternatives:
- **marshmallow or pydantic.** More features, but an extra dependency to learn and explain.
- **MongoDB `$jsonSchema` collection validators.** These enforce rules in the database, but give poor error messages and can't express rules like "start time in the future".

## 5. Data cleaning and generation (`Raw_Dataset/seed.py`)

**Sources.** Two Kaggle CSVs:
- `megaGymDataset.csv`: about 2,900 exercises
- `gym_members_exercise_tracking.csv`: 973 rows of member and session data

### Cleaning

| Issue in the source | What `seed.py` does |
|---|---|
| Duplicate exercise titles | Removed, comparing case-insensitively (9 duplicates). Result: 2,909 unique exercises. |
| Size of the dataset | Trimmed to a manageable size: **300 exercises** (`MAX_EXERCISES`), taken one at a time from each type + body-part group, rated exercises first, so every filter value is still present; and the first **100 member rows** (`MAX_MEMBERS`). |
| Blank rating, or `0.0` meaning "not rated" | Becomes `null` |
| Blank description | Becomes `null` |
| Blank equipment | Becomes `"Other"` |
| Member CSV column names | Renamed to snake_case fields |
| Experience level stored as 1/2/3 | Mapped to Beginner, Intermediate, Expert |
| Numbers stored as text | Converted to proper `int` / `float` types |

### Restructuring

- Each of the first 100 members-CSV rows becomes **one member document**.
- The row's physical measurements are grouped into a `body_metrics` sub-document.
- The row's session figures (frequency, duration, calories, BPM, workout type) are used as **that member's personal averages** for generating their workout history.

### Generated data

Everything below is generated with a fixed random seed (661), so every run produces the same data relative to the day it is run.

| Data | How it is generated |
|---|---|
| **6 branches** | Real Northern Ireland locations with real coordinates as GeoJSON `[lng, lat]`, random facilities, capacity and phone. |
| **Staff** | 1 admin and 18 trainers (3 per branch), each with 2 specialities from the four workout types. |
| **Member identities** | Name and email from first/last-name lists, matching the CSV gender. Emails are kept unique. Usernames are the part of the email before the @. |
| **Memberships** | Plans weighted: Monthly 55%, Quarterly 25%, Annual 15%, Student 5%. 80% are active today; 20% lapsed within the last 60 days. |
| **Workout history** | 8 weeks per member, around their own frequency (±1 day per week). Duration varies by ±15%; calories are scaled from the member's average; BPM is slightly varied. 70% of sessions are the member's preferred workout type. Strength and HIIT sessions include 3–5 exercises from the exercise library, grouped by body part, with sets, reps and weight (`null` for body-weight exercises). Workouts after a lapsed membership's end date are dropped. |
| **Classes** | A weekly timetable of 5 slots per branch, repeated over 4 past and 4 future weeks: 6 × 5 × 8 = **240 classes**. Each slot gets a trainer, a category from their specialities, a title, duration, capacity (12–25) and level. |
| **Bookings** | Demand is 45–105% of capacity for past classes and 10–80% for future ones. Members who prefer the class's workout type are three times as likely to book. Lapsed members can't book. 8% of bookings are cancelled. 85% of active bookings for past classes are marked attended; future ones have `attended: null`. `booked_count` equals the active bookings. |
| **Reviews** | 35% of exercises get 1–4 reviews from random members, with stars weighted towards 4–5 and a comment matching the stars. |

**Passwords.** One bcrypt hash of `Password123!` is shared by all seeded accounts, so seeding takes seconds rather than about 25 seconds for 119 separate hashes (about 0.2 s each). Accounts created through the API hash each password individually.

**Indexes.** All indexes in section 3 are created, except the TTL index, which the API creates.

**Result:** 6 branches, 300 exercises (about 260 reviews), 100 members (about 2,200 workouts), 240 classes (about 2,300 bookings) and 119 users.

The data mixes many types: text, integers, floats, booleans, nulls, dates, arrays, GeoJSON and nested sub-documents up to three levels deep (member → workouts → exercises).

## 6. Validation, errors and status codes

| Code | Used for |
|---|---|
| 200 | Successful reads and updates (updates return the updated resource). Also booking cancellation, which returns a message. |
| 201 | Created. Body: `{"message", "id", "url"}`, plus a `Location` header. |
| 204 | Successful deletes. |
| 400 | Malformed JSON; validation or query-parameter errors; invalid ObjectId; rules such as a past start time, booking a cancelled or past class, attendance before the class. |
| 401 | Missing, invalid, expired or logged-out token; bad login. |
| 403 | Wrong role; someone else's resource; booking without an active membership; staff trying to review or book. |
| 404 | Unknown id (sub-resource errors say which part is missing); unknown URL (JSON handler). |
| 405 | Wrong method on an existing URL (JSON handler listing the allowed methods). |
| 409 | Duplicate username, email, branch name or exercise title; already reviewed; class full; already booked; booking already cancelled; trainer clash; capacity below bookings; deleting a branch that is in use or a class with bookings. |
| 500 | Unexpected exception (JSON handler; details are logged on the server, never sent to the client). |

## 7. Differences from the Biz Directory example

- **JSON request bodies** instead of form data, so numbers, booleans, lists and nested objects keep their types and can be type-checked.
- **Validation** of every body and query field: type, range, enum, format, unknown fields, cross-field rules.
- **Standard error format** and JSON handlers for 404, 405 and 500.
- **Four sub-document resources** with full CRUD (reviews, workouts, bookings and the membership sub-object), using the positional `$`, `$[identifier]` with `array_filters`, `$pull` and the `$elemMatch` projection.
- **Atomic conditional updates** for bookings and reviews.
- **Roles and ownership** (admin, trainer, member) on top of JWT login, plus the blacklist TTL index.
- **Aggregation** throughout (`$facet`, `$lookup` sub-pipelines, `$dateTrunc`, `$dateDiff`, `$filter`, `$sortByCount`), plus `$geoNear` and `$text`.
- **Pagination with totals**, multi-value filters, sorting and case-insensitive collation.
- **Copies of data kept in sync** across collections, with `update_many` and `array_filters`.

## 8. Testing evidence

- **Manual tests per Blueprint during development.** Every endpoint was run against the seeded database, including error cases, with a Python script: auth 17 checks, branches 30, exercises and reviews 33, members and workouts 56, classes and bookings 50+, reports 15.
- **Concurrency test.** 20 parallel booking requests for 3 places gave 3 successes, 17 × 409, and a correct `booked_count`.
- **Postman collection** of 153 requests with 325 `pm.test` assertions in 10 folders. It covers status codes, response shape, filter correctness, sort order, ownership rules and clean-up. Newman result on a freshly seeded database: **153/153 requests, 325/325 assertions passed**. It also passes when run a second time without reseeding.

## 9. Known limitations and possible improvements

- **Registration makes two writes** (member, then user) without a transaction. If the second fails, the first is undone in code (compensating action). A multi-document transaction on a replica set would make it fully atomic.
- **Times are UTC.** The peak-times report groups by UTC hour. In summer (BST) local times are one hour later. `$hour` accepts a `timezone` argument (`Europe/London`) if local grouping is wanted.
- **Stored `status` fields go stale.** Queries compute status from dates instead (section 2). A scheduled job could refresh the stored values.
- **Trainer accounts** can only be created by seeding. A future `POST /users` (admin) endpoint could add staff.
- **No rate limiting** on login. Flask-Limiter could be added to slow down password guessing.

## 10. Use of AI

The specification requires AI use to be acknowledged. Where a chat agent was used, the **chat history (your prompts and the agent's responses)** must be included in the Design and Development document. The code was produced with an AI coding agent (Claude Code), so export the conversation and attach it. Make sure you can explain these in your own words:
- atomic booking
- the stats and report pipelines
- `$geoNear`
- the validation helper
- the JWT and blacklist flow
