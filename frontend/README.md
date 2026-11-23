# PulseFit Web (Angular front end)

The front end for the PulseFit Gym API (`../api`). Built with Angular 19, Bootstrap 5 and Bootstrap Icons.

## Run it

1. Start the API from the `api` folder (see `../api/README.md`): `python app.py`. It runs on port 5001.
2. Install and start the front end from this folder:

   ```bash
   npm install
   npm start
   ```

3. Open http://localhost:4200

Demo logins (password `Password123!`): `oliver.robinson` (member), `sophie.boyle` (trainer), `admin` (admin).

## Tests

```bash
npm test                                                   # watch mode
npx ng test --watch=false --browsers=ChromeHeadless        # run once
npx ng test --watch=false --browsers=ChromeHeadless --code-coverage
```

## Structure

```
src/environments/   environment.ts - the API base URL
src/app/
  models/           TypeScript interfaces for the API data (exercise, gym-class, branch, user, page)
  services/         one service per API resource + api-helpers (query params, error messages)
  interceptors/     auth.interceptor - adds x-access-token, handles expired sessions (401)
  guards/           authGuard (logged in / role check), guestGuard (login + register pages)
  directives/       *appHasRole - structural directive that shows content by role
  pipes/            timeUntil - "in 3 h", "in 2 days"
  shared/           navbar, pagination, star-rating
  pages/            home, login, register, exercise-list, exercise-detail, class-list,
                    branch-list, dashboard, not-found
```

## Pages

| Route | Who | What |
|---|---|---|
| `/` | everyone | Next classes, top rated exercises |
| `/exercises` | everyone | Search and filter the exercise library (filters kept in the URL) |
| `/exercises/:id` | everyone | Exercise details and reviews; members add/edit/delete their own review, admins delete any |
| `/classes` | everyone | Timetable with filters; members book and cancel places |
| `/branches` | everyone | Branches, facilities, opening hours, "find nearest to me" |
| `/login`, `/register` | logged out | Log in (HTTP Basic → JWT) and create a member account |
| `/me` | logged in | Membership details and upcoming/past bookings (members), account info (staff) |
