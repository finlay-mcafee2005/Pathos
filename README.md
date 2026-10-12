<p align="center">
  <img src="frontend/public/pathos-logo.png" alt="Pathos" width="96" />
</p>

<h1 align="center">Pathos</h1>

<p align="center"><b>Running routes picked for how you feel today.</b></p>

<p align="center">
  <a href="https://pathosrun.com"><b>Try it at pathosrun.com →</b></a>
</p>

---

Most route apps answer *"where can I run?"* Pathos answers *"where should I run **today**?"*

Each day you do a quick check-in (energy, sleep, mood, sore spots, how far you want to go and how far you'll travel). Pathos then ranks 700+ real routes around Los Angeles, Glendale and Pasadena for that day, and explains why each one fits.

## Features

- **Daily check-in.** Energy, sleep, mood and run intent (easy, workout, long, explore). A tap-to-select body map marks sore muscles. Includes a "Same as yesterday" shortcut.
- **Personalized recommendations.** Ranked picks with a match score and plain-language reasons, such as "Close match to your planned distance."
- **Travel-aware.** Routes stay within the distance you're willing to travel, with closer starts preferred.
- **Conditions.** Heat, UV, wind and air quality at your planned run time shape the picks.
- **Turn-by-turn Follow view.** Cues for running the route, plus GPX export.
- **Run together.** Friends check in separately and get one shared route that works for everyone. Picks are ranked by the least-ready runner, and faster runners get optional extra laps.
- **Run clubs.** Local club sessions in the coming week are ranked by how well they match your pace and readiness.
- **Run log and stats.** Log runs by hand or import GPX/TCX/FIT files from a watch. Includes weekly mileage, streaks and surface mix.
- **Feedback loop.** After a run, Pathos asks whether the pick fit. Answers are logged so the recommender can be evaluated.

## How the recommender works

Pathos uses a transparent, rules-based scoring engine rather than a black-box model, so every recommendation can be explained.

1. **Candidates.** PostGIS finds visible routes that start within your travel radius.
2. **Readiness.** Your check-in, recent training load and usual pace combine into a readiness level and target distance.
3. **Scoring.** Each route starts at a base score, then gains or loses points for:
   - distance fit
   - terrain and hills versus readiness
   - surface strain on sore or injured areas
   - travel distance
   - scenery and novelty
   - weather
   - your past ratings and surface preferences
4. **Diversity.** Near-duplicate routes are pushed down so the top picks offer real choices.
5. **Group picks.** Routes are scored for each member and combined as half the average fit plus half the lowest member's fit, so no one gets stuck on a route that's wrong for them.

The engine lives in [`backend/app/scoring/`](backend/app/scoring). `scripts/test_scoring.py` runs a quick check without a database.

## Tech stack

| Layer | Tools |
|---|---|
| Frontend | React, TypeScript, Vite, React Leaflet |
| Backend | Python, FastAPI, SQLModel |
| Database | PostgreSQL + PostGIS |
| Routing & data | OSRM (foot profile), OpenStreetMap, Open-Meteo (weather and air quality), Nominatim (geocoding) |
| Hosting | Vercel (frontend), Render (API), Supabase (database) |

## Project structure

```
backend/
  app/
    main.py            API endpoints
    auth.py            password hashing and login tokens
    models.py          database tables
    scoring/           recommendation engine
    directions.py      turn-by-turn cues via OSRM
    conditions.py      weather and air quality
  scripts/             route generation, naming, elevation and data cleanup
frontend/
  src/pages/           check-in, recommendations, run together, stats, ...
  src/components/      nav bar, body map, shared UI
```

## Running it locally

**Requirements:** Python 3.10+, Node 18+ and Docker.

**1. Database**

```bash
docker run -d --name run-recommender-db -p 5432:5432 \
  -e POSTGRES_PASSWORD=devpassword -e POSTGRES_DB=run_recommender \
  postgis/postgis:16-3.4
```

**2. Backend**

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python scripts/create_tables.py
uvicorn app.main:app --reload
```

The API runs at `http://127.0.0.1:8000`, with interactive docs at `/docs`. Route data is built with the scripts in `backend/scripts/`.

**3. Frontend**

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

**Optional: turn-by-turn directions.** Run an OSRM server with the foot profile on port 5001, or set `OSRM_URL` to a public one.

## Configuration

| Variable | Where | Purpose |
|---|---|---|
| `DATABASE_URL` | backend | Postgres connection (defaults to the local Docker database) |
| `AUTH_SECRET` | backend | Secret used to sign login tokens |
| `FRONTEND_ORIGINS` | backend | Comma-separated sites allowed to call the API |
| `OSRM_URL` | backend | Routing server for directions |
| `ADMIN_EMAILS` | backend | Accounts that can see research summaries for all users |
| `VITE_API_URL` | frontend | Address of the backend API |

## Status

Pathos is a student project by Finlay McAfee (Occidental College, Math & Computer Science) and is in active development. Next up: user interviews, a consent flow for research participants, and evaluating recommendation quality from the "did this pick fit?" feedback.
