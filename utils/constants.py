# allowed values for the enum fields (same values as the seeded data)

# membership plan -> number of days (same as seed.py)
PLAN_DAYS = {"Monthly": 30, "Quarterly": 90, "Annual": 365, "Student": 120}
MEMBERSHIP_STATUSES = ["active", "expired"]

GENDERS = ["Male", "Female"]
EXPERIENCE_LEVELS = ["Beginner", "Intermediate", "Expert"]
WORKOUT_TYPES = ["Cardio", "HIIT", "Strength", "Yoga"]      # also the class categories

CLASS_LEVELS = ["Beginner", "All levels", "Intermediate", "Advanced"]
CLASS_STATUSES = ["scheduled", "completed", "cancelled"]
BOOKING_STATUSES = ["booked", "cancelled"]

EXERCISE_TYPES = ["Cardio", "Olympic Weightlifting", "Plyometrics", "Powerlifting",
                  "Strength", "Stretching", "Strongman"]
BODY_PARTS = ["Abdominals", "Abductors", "Adductors", "Biceps", "Calves", "Chest", "Forearms",
              "Glutes", "Hamstrings", "Lats", "Lower Back", "Middle Back", "Neck", "Quadriceps",
              "Shoulders", "Traps", "Triceps"]
EQUIPMENT = ["Bands", "Barbell", "Body Only", "Cable", "Dumbbell", "E-Z Curl Bar", "Exercise Ball",
             "Foam Roll", "Kettlebells", "Machine", "Medicine Ball", "None", "Other"]
EXERCISE_LEVELS = ["Beginner", "Intermediate", "Expert"]

ROLES = ["admin", "trainer", "member"]

# ?pn=<page number>&ps=<page size> - added to the query rules of every list route
PAGINATION_QUERY = {
    "pn": {"type": "int", "min": 1, "default": 1},
    "ps": {"type": "int", "min": 1, "max": 100, "default": 10},
}
