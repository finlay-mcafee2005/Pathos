"""
Seeds manually curated real running clubs for the Glendale/Pasadena/
Eagle Rock area, with join codes and weekly meetup schedules.

Run with: python3 scripts/seed_clubs.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlmodel import Session, create_engine

from app.models import Club, ClubSchedule

DATABASE_URL = "postgresql://postgres:devpassword@localhost:5432/run_recommender"
engine = create_engine(DATABASE_URL)

CLUBS = [
    {
        "name": "Pasadena Pacers",
        "location": "Pasadena, CA",
        "pace_range": "7:30-9:00 min/mi",
        "experience_level": "intermediate",
        "join_code": "PASADENA1",
        "schedules": [("saturday", "07:30"), ("wednesday", "18:00")],
    },
    {
        "name": "Glendale Trail Runners",
        "location": "Glendale, CA",
        "pace_range": "8:00-10:00 min/mi",
        "experience_level": "beginner",
        "join_code": "GLENDALE1",
        "schedules": [("sunday", "08:00")],
    },
    {
        "name": "Eagle Rock Run Club",
        "location": "Eagle Rock, CA",
        "pace_range": "6:30-8:00 min/mi",
        "experience_level": "advanced",
        "join_code": "EAGLEROCK1",
        "schedules": [("tuesday", "18:30"), ("saturday", "08:00")],
    },
]

with Session(engine) as session:
    for club_data in CLUBS:
        schedules = club_data.pop("schedules")
        club = Club(**club_data)
        session.add(club)
        session.commit()
        session.refresh(club)

        for day, time in schedules:
            session.add(ClubSchedule(club_id=club.id, day_of_week=day, meetup_time=time))

        print(f"Added '{club.name}' (code: {club.join_code})")

    session.commit()
    print("Done.")
