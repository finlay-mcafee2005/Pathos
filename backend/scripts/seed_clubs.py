"""
Real group runs in the Glendale / Pasadena / Eagle Rock / Highland Park area.

Researched Oct 7, 2026 from the clubs' own pages, local press and the
community-maintained LA Running Connoisseur list. Distances and paces are
only filled in where a source states them - otherwise left blank (the
matcher treats blanks as neutral). Schedules change: re-check sources
before relying on them, and update VERIFIED_ON when you do.

Join codes are Pathos-internal (for linking a user to a club), not the
clubs' own.

Meeting spots are geocoded from their addresses with Nominatim when the
script runs, so it needs internet access.

Run with: python3 scripts/seed_clubs.py   (start the backend once first)
"""

import sys
import os
import time
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlmodel import Session, create_engine, select

from app.models import Club, ClubSchedule, User
from app.geocoding import geocode_address

DATABASE_URL = "postgresql://postgres:devpassword@localhost:5432/run_recommender"
engine = create_engine(DATABASE_URL)

VERIFIED_ON = date(2026, 10, 7)
LA_LIST = "https://larunningconnoisseur.com/los-angeles-run-clubs-list/"
ALL_PACES = "All paces"

# sessions: (day, time, distance_mi or None, run_type, surface or None)
CLUBS = [
    {
        "name": "Run With Us — Monday Fun Run",
        "location": "235 N Lake Ave, Pasadena, CA",
        "pace_range": ALL_PACES,
        "experience_level": "all",
        "join_code": "RUNWITHUS",
        "source_url": "https://www.pasadenanow.com/weekendr/free-weekly-run-welcomes-all-paces/",
        "notes": "Free, no registration. 4 or 6 mi run, or 2 mi walk. Meets in the lot behind the store; first Monday of the month at the Rose Bowl instead.",
        "sessions": [("monday", "18:00", 4, "social", "road")],
    },
    {
        "name": "Pasadena Run Club (lululemon)",
        "location": "103 W Colorado Blvd, Pasadena, CA",
        "pace_range": ALL_PACES,
        "experience_level": "all",
        "join_code": "PASRUNCLUB",
        "source_url": "https://laist.com/events/weekly-lululemon-pasadena-run-walk-club",
        "notes": "Free, no RSVP. Meet at 6:00, run at 6:30. 3 or 5 mi run, or 2.5 mi power walk.",
        "sessions": [("wednesday", "18:30", 3, "social", "road")],
    },
    {
        "name": "Pasadena Pacers",
        "location": "360 N Arroyo Blvd, Pasadena, CA",
        "pace_range": "Beginner-friendly",
        "experience_level": "beginner",
        "join_code": "PASADENA1",
        "source_url": "https://runpacers.org/pasadena/",
        "notes": "Meets just south of the Rose Bowl Aquatic Center, south end of Lot I. Rose Bowl events can move it - check their calendar. Saturday start time varies (listed as 7 or 8 am).",
        "sessions": [
            ("tuesday", "18:00", None, "easy", "road"),
            ("thursday", "18:00", None, "easy", "road"),
            ("saturday", "07:00", None, "long", "road"),
        ],
    },
    {
        "name": "Dog Haus Running Club",
        "location": "Dog Haus Biergarten, 93 E Green St, Pasadena, CA",
        "pace_range": ALL_PACES,
        "experience_level": "all",
        "join_code": "DOGHAUS",
        "source_url": "https://sites.google.com/ffprunningclubs.org/doghausrunningclub",
        "notes": "Free 5K. Sources list the start as 6:00 or 6:30 pm.",
        "sessions": [("tuesday", "18:30", 3.1, "social", "road")],
    },
    {
        "name": "Eagle Rock Run Club",
        "location": "The Oinkster, 2005 Colorado Blvd, Los Angeles, CA",
        "pace_range": ALL_PACES,
        "experience_level": "all",
        "join_code": "EAGLEROCK1",
        "source_url": "https://www.theeastsiderla.com/neighborhoods/eagle_rock/eagle-rock-run-club-helps-locals-find-fitness-and-friendship/article_1bc2a932-4d1d-41c0-9d6c-c899de0667df.html",
        "notes": "Thursday evening run from The Oinkster; Monday 7 am 'Java Jog' from Eagle Rock coffee shops (location rotates). Longer weekend trail runs announced on their Instagram.",
        "sessions": [
            ("thursday", "19:00", None, "social", "road"),
            ("monday", "07:00", None, "easy", "road"),
        ],
    },
    {
        "name": "LA Frontrunners — Oxy Track",
        "location": "Occidental College, 1600 Campus Rd, Los Angeles, CA",
        "pace_range": ALL_PACES,
        "experience_level": "all",
        "join_code": "FRONTRUN",
        "source_url": LA_LIST,
        "notes": "Track session at Occidental College. A fee applies.",
        "sessions": [("thursday", "18:30", None, "workout", "track")],
    },
    {
        "name": "Glendale Run Club",
        "location": "lululemon, 889 Americana Way, Glendale, CA",
        "pace_range": ALL_PACES,
        "experience_level": "all",
        "join_code": "GLENDALE1",
        "source_url": "https://www.glendalerunclub.com/",
        "notes": "Wednesday from lululemon at The Americana; also Thursday 6:30 pm from Homestate in Atwater Village.",
        "sessions": [
            ("wednesday", "18:30", None, "social", "road"),
            ("thursday", "18:30", None, "social", "road"),
        ],
    },
    {
        "name": "Garvanza Run Club",
        "location": "Garvanza Park, 6240 Meridian St, Los Angeles, CA",
        "pace_range": ALL_PACES,
        "experience_level": "all",
        "join_code": "GARVANZA",
        "source_url": LA_LIST,
        "notes": "Listed on a community-maintained list only; confirm before going.",
        "sessions": [("sunday", "08:15", None, "easy", "road")],
    },
]

KEEP_CODES = {c["join_code"] for c in CLUBS}

with Session(engine) as session:
    # remove clubs from the old placeholder seed that aren't in this list
    for old in session.exec(select(Club)).all():
        if old.join_code not in KEEP_CODES:
            for u in session.exec(select(User).where(User.club_id == old.id)).all():
                u.club_id = None
                session.add(u)
            for s in session.exec(select(ClubSchedule).where(ClubSchedule.club_id == old.id)).all():
                session.delete(s)
            session.delete(old)
            print(f"Removed placeholder club: {old.name}")
    session.commit()

    for data in CLUBS:
        data = dict(data)
        sessions = data.pop("sessions")
        try:
            lat, lon = geocode_address(data["location"])
        except Exception as e:
            lat = lon = None
            print(f"  (couldn't geocode {data['location']}: {e})")
        time.sleep(1.1)   # Nominatim allows 1 request per second

        club = session.exec(select(Club).where(Club.join_code == data["join_code"])).first()
        if club is None:
            club = Club(**data)
        else:
            for key, value in data.items():
                setattr(club, key, value)
        club.latitude, club.longitude = lat, lon
        club.verified_on = VERIFIED_ON
        session.add(club)
        session.commit()
        session.refresh(club)

        for old in session.exec(select(ClubSchedule).where(ClubSchedule.club_id == club.id)).all():
            session.delete(old)
        for day, t, miles, run_type, surface in sessions:
            session.add(ClubSchedule(club_id=club.id, day_of_week=day, meetup_time=t,
                                     distance_mi=miles, run_type=run_type, surface=surface))
        session.commit()
        where = f"{lat:.4f}, {lon:.4f}" if lat is not None else "no coordinates"
        print(f"Seeded {club.name} ({len(sessions)} sessions, {where})")
