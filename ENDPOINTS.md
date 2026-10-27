# API Endpoint Summary

**PulseFit Gym and Fitness Class Booking API**. Base URL: `http://127.0.0.1:5001/api/v1.0`

51 endpoints in 9 Blueprints.

**Authentication.** Log in with `GET /auth/login` using HTTP Basic auth. Send the returned JWT in the `x-access-token` header.

**Access levels used in the tables:**

| Access | Meaning |
|---|---|
| Public | No token needed |
| Any user | Any valid token |
| Member | A member account (staff accounts have no member record) |
| Self or admin | The member who owns the record, or an admin |
| Owner trainer | The trainer who teaches the class |

**Request format.**
- Request bodies are JSON (`Content-Type: application/json`). Unknown fields are rejected.
- `PUT` updates only the fields sent.
- List endpoints accept `pn` (page, default 1) and `ps` (page size 1–100, default 10). They return `{"data": [...], "pagination": {"page", "page_size", "total", "pages"}}`.

**Errors** are returned as `{"error": "<message>", "details": {...}}`:

| Status | When |
|---|---|
| 400 | Invalid input |
| 401 | Missing, invalid, expired or logged-out token |
| 403 | Wrong role, or someone else's resource |
| 404 | Not found |
| 405 | Wrong HTTP method |
| 409 | Conflict (duplicate, full class, already booked, resource in use) |
| 500 | Unexpected server error |

## Auth (`blueprints/auth`)

| Method | URL | Access | Purpose |
|---|---|---|---|
| POST | `/auth/register` | Public | Create a member login account and its linked member record (active membership, BMI calculated). 201 / 400 / 409 |
| GET | `/auth/login` | Public (Basic auth) | Check username and password (bcrypt) and return a JWT valid for 8 minutes containing `user_id`, `username`, `role`, `member_id`. 200 / 401 |
| GET | `/auth/logout` | Any user | Add the current token to the blacklist so it can no longer be used. 200 / 401 |
| GET | `/auth/me` | Any user | The logged-in account (without the password) and, for members, a membership summary. 200 / 401 |

## Branches (`blueprints/branches`)

| Method | URL | Access | Purpose |
|---|---|---|---|
| GET | `/branches` | Public | List branches. Filters: `city`, `facility` (comma-separated, all must match), `q` (name/area search). Paginated. |
| POST | `/branches` | Admin | Create a branch. `lat`/`lng` are stored as a GeoJSON Point. 201 / 400 / 409 duplicate name |
| GET | `/branches/near?lat=&lng=&km=&limit=` | Public | Branches within `km` (0–100, default 10) of a point, nearest first, with `distance_km` (`$geoNear` on the 2dsphere index). |
| GET | `/branches/<id>` | Public | One branch. 400 invalid id / 404 |
| PUT | `/branches/<id>` | Admin | Update some fields. Nested `address` and `opening_hours` can be updated one sub-field at a time. A rename also updates the branch name copied into its classes. 409 duplicate name |
| DELETE | `/branches/<id>` | Admin | Delete a branch. 409 if members, trainers or upcoming classes still use it. 204 |
| GET | `/branches/<id>/classes` | Public | The branch's upcoming scheduled classes, soonest first, with `spaces_left`. Filter: `category`. Paginated. |

## Exercises (`blueprints/exercises`)

| Method | URL | Access | Purpose |
|---|---|---|---|
| GET | `/exercises` | Public | Search the library. Filters (comma-separated → `$in`): `body_part`, `equipment`, `level`, `type`. Also `min_rating`, `q` (full-text search on title and description), `sort` = `rating` / `title` / `reviews`, `order` = `asc` / `desc`. Adds `review_count` and `avg_stars`. Paginated. |
| POST | `/exercises` | Admin, trainer | Create an exercise. 201 / 400 / 409 duplicate title |
| GET | `/exercises/filters` | Public | Distinct values (with counts) for `body_part`, `equipment`, `level` and `type`, for building filter menus. |
| GET | `/exercises/top-rated?body_part=&min_reviews=&limit=` | Public | Highest average review stars (aggregation). Exercises with fewer than `min_reviews` reviews are ignored. |
| GET | `/exercises/<id>` | Public | One exercise with its reviews, `review_count` and `avg_stars`. |
| PUT | `/exercises/<id>` | Admin, trainer | Update some fields. 409 duplicate title |
| DELETE | `/exercises/<id>` | Admin, trainer | Delete an exercise. 204 |

## Exercise reviews: sub-documents (`blueprints/reviews`)

| Method | URL | Access | Purpose |
|---|---|---|---|
| GET | `/exercises/<id>/reviews?sort=newest\|oldest\|stars` | Public | All reviews of an exercise with the average stars. |
| POST | `/exercises/<id>/reviews` | Member | Add a review (`stars` 1–5, `comment`). One review per member per exercise, checked atomically. 201 / 409 |
| GET | `/exercises/<id>/reviews/<review_id>` | Public | One review. 404 says whether the exercise or the review is missing. |
| PUT | `/exercises/<id>/reviews/<review_id>` | Review author | Edit your own review. 403 for anyone else |
| DELETE | `/exercises/<id>/reviews/<review_id>` | Author or admin | Delete a review (admins can moderate any review). 204 |

## Members (`blueprints/members`)

| Method | URL | Access | Purpose |
|---|---|---|---|
| GET | `/members` | Admin | List members. Filters: `branch`, `status` (`active` / `expired`, worked out from the end date), `plan`, `workout_type`, `gender`, `q` (name/email). `sort` = `name` / `joined_at` / `age` / `end_date`. Paginated. |
| POST | `/members` | Admin | Create a member record without a login account (front-desk sign-up). 201 / 409 duplicate email |
| GET | `/members/<id>` | Self or admin | One member with `workout_count` and home branch name. |
| PUT | `/members/<id>` | Self or admin | Update profile fields. BMI is recalculated. Only admins can change the email (also updated on the login account). A name change is copied into the member's bookings and reviews. |
| DELETE | `/members/<id>` | Admin | Delete a member and their login account, remove their reviews and free their upcoming class places. 204 |
| PUT | `/members/<id>/membership` | Admin | Renew or change plan. An active membership is extended from its end date; an expired one restarts today. |
| GET | `/members/<id>/stats?weeks=` | Self or admin | Workout statistics for the last 1–52 weeks (default 8): totals, weekly breakdown, favourite workout type, sessions by type and most-used exercises (one aggregation). |
| GET | `/members/<id>/bookings?status=&when=` | Self or admin | The member's bookings across all classes with class details. `when` = `upcoming` / `past` / `all`. Paginated. |

## Workouts: sub-documents (`blueprints/workouts`)

| Method | URL | Access | Purpose |
|---|---|---|---|
| GET | `/members/<id>/workouts` | Self or admin | Workout log, newest first. Filters: `from`, `to` (ISO dates), `type`. `sort` = `newest` / `oldest`. Paginated. |
| POST | `/members/<id>/workouts` | Self or admin | Log a workout, optionally with exercises performed. Checks: no future dates, `max_bpm` ≥ `avg_bpm`, every `exercise_id` exists. 201 |
| GET | `/members/<id>/workouts/<workout_id>` | Self or admin | One workout. |
| PUT | `/members/<id>/workouts/<workout_id>` | Self or admin | Update some fields. The cross-field rules are checked again. |
| DELETE | `/members/<id>/workouts/<workout_id>` | Self or admin | Delete a workout. 204 |

## Classes (`blueprints/classes`)

| Method | URL | Access | Purpose |
|---|---|---|---|
| GET | `/classes` | Public | Timetable sorted by start time, with `spaces_left`. Filters: `branch`, `trainer`, `category`, `level`, `status`, `when` (`upcoming` default / `past` / `all`), `from`, `to`, `available=true` (bookable places left), `q`. Paginated. |
| POST | `/classes` | Admin, trainer | Create a class. Trainers can only create classes they teach. The start time must be in the future. 409 if the trainer has an overlapping class. 201 |
| GET | `/classes/<id>` | Public | One class (the bookings list is not public). |
| PUT | `/classes/<id>` | Admin, owner trainer | Update a class. Only admins can reassign the trainer. Capacity cannot drop below `booked_count` (409). `status: "cancelled"` also cancels every booking. |
| DELETE | `/classes/<id>` | Admin, owner trainer | Delete a class. 409 if it still has active bookings (cancel it first). 204 |

## Bookings: sub-documents (`blueprints/bookings`)

| Method | URL | Access | Purpose |
|---|---|---|---|
| POST | `/classes/<id>/bookings` | Member | **Atomic booking.** Requires an active membership covering the class date (403). 400 if the class is cancelled or past; 409 if it is full or already booked. 201 with `spaces_left` |
| GET | `/classes/<id>/bookings?status=` | Admin, owner trainer | All bookings with a summary (booked, cancelled, attended, no-shows). |
| GET | `/classes/<id>/bookings/<booking_id>` | Booker, owner trainer, admin | One booking with class details. |
| DELETE | `/classes/<id>/bookings/<booking_id>` | Booker, owner trainer, admin | Cancel a booking before the class starts. Sets the status to cancelled and decrements `booked_count` atomically. 409 if already cancelled |
| PUT | `/classes/<id>/bookings/<booking_id>/attendance` | Admin, owner trainer | Record `attended: true/false` once the class has started. Also marks the class completed. |

## Reports (`blueprints/reports`): admin only, all aggregation pipelines

| Method | URL | Access | Purpose |
|---|---|---|---|
| GET | `/reports/popular-classes` | Admin | Bookings, fill rate and attendance rate by class title and by category. Filters: `from`, `to`, `branch`, `category`. `sort` = `bookings` / `fill_rate` / `attendance_rate`; `limit`. |
| GET | `/reports/branch-usage` | Admin | Per branch: members, active members, classes, bookings, fill rate, attendance rate, bookings per active member. Filters: `from`, `to`. |
| GET | `/reports/peak-times` | Admin | Busiest weekday/hour slots, plus bookings by weekday and by hour (UTC). Filters: `from`, `to`, `branch`; `limit`. |
| GET | `/reports/trainer-performance` | Admin | Per trainer: classes taught, upcoming classes, bookings, fill rate, attendance rate, specialities, branch. `sort` = `attendance_rate` / `fill_rate` / `classes_taught`. |
| GET | `/reports/membership-summary` | Admin | Members by status and by plan, and memberships expiring within `days` (1–365, default 30). Filter: `branch`; `limit` for the list. |
