"""
Re-grades every route's difficulty from distance + elevation gain using the
shared rule in app/scoring/difficulty.py. No API calls - instant.

Run with: python3 scripts/update_difficulty.py
(update_elevation.py also does this for each route it updates.)
"""

import sys
import os
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlmodel import Session, create_engine, select

from app.models import Route
from app.scoring.difficulty import classify_difficulty

DATABASE_URL = "postgresql://postgres:devpassword@localhost:5432/run_recommender"

engine = create_engine(DATABASE_URL)

with Session(engine) as session:
    routes = session.exec(select(Route)).all()
    before, after, changed = Counter(), Counter(), 0
    for r in routes:
        new = classify_difficulty(r.distance_km, r.elevation_gain_m or 0)
        before[r.difficulty] += 1
        after[new] += 1
        if new != r.difficulty:
            changed += 1
            r.difficulty = new
            session.add(r)
    session.commit()

    print(f"Re-graded {len(routes)} routes ({changed} changed).")
    for level in ("easy", "moderate", "hard"):
        print(f"  {level:<9} {before[level]:>4} -> {after[level]:>4}")
