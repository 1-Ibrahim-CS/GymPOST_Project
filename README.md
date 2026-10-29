# PulseFit: Gym and Fitness Class Booking API

The back end for a gym chain with several branches: a RESTful **Python Flask** API over a **MongoDB** database (COM661 Full Stack Strategies and Development, CW1).

Members can:
- browse and search a library of 300 exercises and review them
- find the nearest branch
- book and cancel class places (never overbooked)
- log workouts and see their progress statistics

Trainers manage their classes and record attendance. Admins manage branches, members and memberships, and get management reports.

- **Endpoints:** see [ENDPOINTS.md](ENDPOINTS.md) (51 endpoints in 9 Blueprints)
- **Design and algorithms:** see [DESIGN_NOTES.md](DESIGN_NOTES.md)
- **Tests:** [postman/GymAPI.postman_collection.json](postman/GymAPI.postman_collection.json) (153 requests, 325 assertions)

## Project structure

```
app.py                  creates the Flask app, registers the Blueprints, JSON error handlers
globals.py              configuration (.env), the MongoDB connection, and OPTIONS + SCHEMAS read from the database
decorators.py           @jwt_required and @role_required(...)
utils/
  validation.py         schema-based validation of JSON bodies and query strings, and the ?pn=&ps= paging rules
  serialize.py          JSON provider: ObjectId -> string, datetime -> ISO 8601
blueprints/
  auth/ branches/ exercises/ reviews/ members/ workouts/ classes/ bookings/ reports/
                        (members.py also has the member helpers: BMI, new membership, new member document)
Raw_Dataset/
  seed.py               builds the gymDB database from the two Kaggle CSVs, plus the options and schemas collections
  megaGymDataset.csv, gym_members_exercise_tracking.csv
postman/
  GymAPI.postman_collection.json, GymAPI.postman_environment.json
```

## Requirements

- Python 3.10 or later
- MongoDB 5.0 or later. Either a local server or Atlas. Version 5.0 is needed for `$dateTrunc`, `$dateDiff` and `$lookup` with both `localField` and `pipeline`.
- Node.js, only to run the Postman tests from the command line with Newman

## Setup

Run these commands from the project folder.

1. Create and activate a virtual environment, then install the dependencies.

   ```bash
   python -m venv .venv
   .venv\Scripts\activate          # Windows
   source .venv/bin/activate       # macOS / Linux
   pip install -r requirements.txt
   ```

2. Configure the database connection. Copy `.env.example` to `.env` and set `MONGODB_URI` and `SECRET_KEY`. `seed.py` and the API both read this file, so they always use the same database. `.env` is listed in `.gitignore`: never commit it.

   ```
   MONGODB_URI=mongodb://127.0.0.1:27017                   # local MongoDB
   # MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/   # or Atlas
   SECRET_KEY=<long random string>                         # required
   FLASK_DEBUG=1                                           # optional, development only
   ```

   Make a `SECRET_KEY` with `python -c "import secrets; print(secrets.token_hex(32))"`. The API refuses to start without one. If `MONGODB_URI` is not set, `mongodb://127.0.0.1:27017` is used. A variable already set in the shell overrides the file.

3. Seed the database. Run this from inside `Raw_Dataset`, because the script opens the CSV files by relative path. It drops and rebuilds the `gymDB` database each time.

   ```bash
   cd Raw_Dataset
   python seed.py
   cd ..
   ```

4. Start the API on http://127.0.0.1:5001. All routes are under `/api/v1.0`.

   ```bash
   python app.py
   ```

## Usage

Every route is under `http://127.0.0.1:5001/api/v1.0`. The full list is in [ENDPOINTS.md](ENDPOINTS.md).

1. **Log in** with Basic Auth to get a token (valid for 8 minutes):

   ```bash
   curl -u admin:Password123! http://127.0.0.1:5001/api/v1.0/auth/login
   ```

2. **Send the token** in the `x-access-token` header on protected routes:

   ```bash
   curl -H "x-access-token: <token>" http://127.0.0.1:5001/api/v1.0/members?ps=5
   ```

3. **Public routes** need no token, e.g. `GET /branches`, `GET /exercises?q=squat`, `GET /classes`.
4. **Log out** with `GET /auth/logout` (with the token) to block the token before it expires.

Request bodies are JSON (`Content-Type: application/json`). Errors always come back as `{"error": ..., "details": {...}}`.

## Seeded logins

Every seeded account uses the password **`Password123!`**.

| Role | Username | Notes |
|---|---|---|
| admin | `admin` | Full access, including reports |
| trainer | `sophie.boyle` | 18 trainers in total (3 per branch). Usernames are the first part of their email address. |
| member | `oliver.robinson` | 100 members. Usernames are the first part of their email address, e.g. `firstname.lastname`. |

Log in with `GET /api/v1.0/auth/login` using **Basic Auth**, then send the returned token in the `x-access-token` header.

## Testing with Postman

1. Import `postman/GymAPI.postman_collection.json` and `postman/GymAPI.postman_environment.json` into Postman, then select the **PulseFit Local** environment.
2. Open the collection and click **Run**. Run all ten folders in order.

The run handles its own data:
- It logs in, registers its own test members and saves tokens and ids into collection variables automatically.
- It creates a branch, an exercise and a class, and deletes everything it created at the end. You can repeat the run without reseeding.

To run it from the command line:

```bash
npx newman run postman/GymAPI.postman_collection.json -e postman/GymAPI.postman_environment.json
```

Expected result: 153 requests and 325 assertions, 0 failures.

For the submission printouts:
- **Test results:** export or print the Collection Runner results.
- **API documentation:** in Postman, open the collection → **View documentation** → publish or print. Every folder and request has a description.

## Exporting the collections (submission)

The submission needs one JSON file per collection, made with `mongoexport`. This is part of the free **MongoDB Database Tools** (https://www.mongodb.com/try/download/database-tools). Add its `bin` folder to your PATH.

**Local database:**

```bash
mongoexport --uri="mongodb://127.0.0.1:27017/gymDB" --collection=branches  --out=export/branches.json
mongoexport --uri="mongodb://127.0.0.1:27017/gymDB" --collection=exercises --out=export/exercises.json
mongoexport --uri="mongodb://127.0.0.1:27017/gymDB" --collection=members   --out=export/members.json
mongoexport --uri="mongodb://127.0.0.1:27017/gymDB" --collection=classes   --out=export/classes.json
mongoexport --uri="mongodb://127.0.0.1:27017/gymDB" --collection=users     --out=export/users.json
mongoexport --uri="mongodb://127.0.0.1:27017/gymDB" --collection=options   --out=export/options.json
mongoexport --uri="mongodb://127.0.0.1:27017/gymDB" --collection=schemas   --out=export/schemas.json
```

**Atlas:** use your connection string with the database name added:

```bash
mongoexport --uri="mongodb+srv://<user>:<password>@<cluster>.mongodb.net/gymDB" --collection=branches --out=export/branches.json
```

All seven collections in one loop:

```bash
# bash
for c in branches exercises members classes users options schemas; do
  mongoexport --uri="mongodb://127.0.0.1:27017/gymDB" --collection=$c --out=export/$c.json
done
```

```powershell
# PowerShell
foreach ($c in "branches","exercises","members","classes","users","options","schemas") {
  mongoexport --uri="mongodb://127.0.0.1:27017/gymDB" --collection=$c --out="export/$c.json"
}
```

Add `--jsonArray` if you want each file to be a single JSON array instead of one document per line.

`export/blacklist.json` is deliberately left empty. The `blacklist` collection only holds logged-out tokens, which expire after 8 minutes and are deleted automatically, so exporting them would only put tokens into the repository.

### Document models

`export/models/` has one `<collection>.schema.json` per collection describing what each document looks like: every field, its BSON type, which fields are required, the allowed values and ranges, embedded arrays (reviews, workouts, bookings) and which ids reference other collections. They are written as MongoDB `$jsonSchema` validators, and every document in the exported data matches its model.

To see or enforce one in Compass, open the collection → **Validation** tab and paste the file contents. In `mongosh`:

```js
db.runCommand({ collMod: "members", validator: <contents of members.schema.json>, validationLevel: "moderate" })
```

## Security considerations

- **Secrets stay out of the code.** `MONGODB_URI` and `SECRET_KEY` are read from `.env`, which is git-ignored. The API will not start without a `SECRET_KEY`, so there is no built-in default key.
- **Passwords** are hashed with bcrypt and never returned by the API. Login gives the same 401 for an unknown user and a wrong password, so usernames can't be discovered.
- **Tokens** are JWTs (HS256) that expire after 8 minutes. Logout blacklists the token; a TTL index removes it from the blacklist once it would have expired anyway.
- **Access control.** Every route that changes data needs a token: `@jwt_required`, or `@role_required(...)`, which checks the token first and then the role. Ownership is checked inside the routes (members only see and edit their own record, workouts, bookings and reviews). Only `POST /auth/register` and `GET /auth/login` are public, by design.
- **Input validation.** Every request body is checked against a schema (stored in the `schemas` collection); unknown fields are rejected, and ids, dates, ranges, choices and patterns are validated before any query runs.
- **Debug mode is off by default.** Flask's debugger can run code, so it is only enabled when `FLASK_DEBUG=1` is set in `.env` on a development machine.
- **Demo data.** The seeded accounts all use `Password123!` so the API can be tested and demonstrated. `seed.py` uses Python's `random` only to generate fake demo data, never for anything security-related.
- **Known limitations:** no rate limiting on login and no HTTPS in the development server. See [DESIGN_NOTES.md](DESIGN_NOTES.md).

## Data sources

- [Gym Exercise Data](https://www.kaggle.com/datasets/niharika41298/gym-exercise-data) (`megaGymDataset.csv`)
- [Gym Members Exercise Dataset](https://www.kaggle.com/datasets/valakhorasani/gym-members-exercise-dataset) (`gym_members_exercise_tracking.csv`)

Branches, trainers, classes, bookings, workout history and reviews are generated by `seed.py`. See [DESIGN_NOTES.md](DESIGN_NOTES.md).
