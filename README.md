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
globals.py              configuration (.env) and the MongoDB connection
decorators.py           @jwt_required and @role_required(...)
utils/
  validation.py         schema-based validation of JSON bodies and query strings
  serialize.py          JSON provider: ObjectId -> string, datetime -> ISO 8601
  membership.py         member profile rules shared by register and members
  constants.py          allowed enum values and the ?pn=&ps= paging rules
blueprints/
  auth/ branches/ exercises/ reviews/ members/ workouts/ classes/ bookings/ reports/
Raw_Dataset/
  seed.py               builds the gymDB database from the two Kaggle CSVs
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

2. Configure the database connection. Copy `.env.example` to `.env` and set `MONGODB_URI`. `seed.py` and the API both read this file, so they always use the same database.

   ```
   MONGODB_URI=mongodb://127.0.0.1:27017                   # local MongoDB
   # MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/   # or Atlas
   SECRET_KEY=change-this-to-a-long-random-string
   ```

   If `MONGODB_URI` is not set, `mongodb://127.0.0.1:27017` is used. A variable already set in the shell overrides the file.

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

## Seeded logins

Every seeded account uses the password **`Password123!`**.

| Role | Username | Notes |
|---|---|---|
| admin | `admin` | Full access, including reports |
| trainer | `sophie.boyle` | 18 trainers in total (3 per branch). Usernames are the first part of their email address. |
| member | `oliver.robinson` | 100 members. Usernames are the first part of their email address, e.g. `firstname.lastname`. |

Log in with `POST /api/v1.0/auth/login` using **Basic Auth**, then send the returned token in the `x-access-token` header.

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
mongoexport --uri="mongodb://127.0.0.1:27017/gymDB" --collection=blacklist --out=export/blacklist.json
```

**Atlas:** use your connection string with the database name added:

```bash
mongoexport --uri="mongodb+srv://<user>:<password>@<cluster>.mongodb.net/gymDB" --collection=branches --out=export/branches.json
```

All six collections in one loop:

```bash
# bash
for c in branches exercises members classes users blacklist; do
  mongoexport --uri="mongodb://127.0.0.1:27017/gymDB" --collection=$c --out=export/$c.json
done
```

```powershell
# PowerShell
foreach ($c in "branches","exercises","members","classes","users","blacklist") {
  mongoexport --uri="mongodb://127.0.0.1:27017/gymDB" --collection=$c --out="export/$c.json"
}
```

Add `--jsonArray` if you want each file to be a single JSON array instead of one document per line.

## Data sources

- [Gym Exercise Data](https://www.kaggle.com/datasets/niharika41298/gym-exercise-data) (`megaGymDataset.csv`)
- [Gym Members Exercise Dataset](https://www.kaggle.com/datasets/valakhorasani/gym-members-exercise-dataset) (`gym_members_exercise_tracking.csv`)

Branches, trainers, classes, bookings, workout history and reviews are generated by `seed.py`. See [DESIGN_NOTES.md](DESIGN_NOTES.md).
