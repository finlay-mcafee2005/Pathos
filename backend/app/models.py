"""
SQLModel schema for the running route recommendation app.

Requires:
    pip install sqlmodel geoalchemy2 psycopg2-binary

Notes:
- gps_path uses GeoAlchemy2's Geometry type since SQLModel/SQLAlchemy
  don't natively support PostGIS geometry columns.
- Enums are plain strings with a Literal-style comment rather than
  Python enums, to keep querying/filtering simple with SQLModel.
  Swap for a real Enum later if you want stricter validation.
"""

from datetime import date, datetime
from typing import Optional, List
from uuid import UUID, uuid4

from sqlmodel import SQLModel, Field, Relationship
from geoalchemy2 import Geometry
from sqlalchemy import Column


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class User(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str

    # "beginner" | "intermediate" | "advanced"
    fitness_level: str = Field(default="beginner")
    weekly_mileage_avg: float = Field(default=0.0)

    created_at: datetime = Field(default_factory=datetime.utcnow)

    runs: List["Run"] = Relationship(back_populates="user")
    checkins: List["Checkin"] = Relationship(back_populates="user")
    injuries: List["Injury"] = Relationship(back_populates="user")
    recommendations: List["Recommendation"] = Relationship(back_populates="user")


# ---------------------------------------------------------------------------
# Injury (longer-lived than a daily checkin's soreness score)
# ---------------------------------------------------------------------------

class Injury(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)

    body_part: str          # e.g. "left_knee", "right_calf"
    severity: str            # "mild" | "moderate" | "severe"
    reported_at: date
    resolved_at: Optional[date] = None  # null = still active

    user: User = Relationship(back_populates="injuries")


# ---------------------------------------------------------------------------
# Daily check-in (mental + physical state, independent of whether they ran)
# ---------------------------------------------------------------------------

class Checkin(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)

    checkin_date: date = Field(index=True)
    soreness_score: int = Field(ge=0, le=10)   # 0 = none, 10 = severe
    energy_score: int = Field(ge=0, le=10)     # 0 = exhausted, 10 = great
    sleep_hours: Optional[float] = None
    mood_tag: Optional[str] = None             # e.g. "stressed", "motivated"

    user: User = Relationship(back_populates="checkins")


# ---------------------------------------------------------------------------
# Route (the thing being recommended)
# ---------------------------------------------------------------------------

class Route(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str

    distance_km: float
    elevation_gain_m: float
    surface_type: str        # "pavement" | "trail" | "track" | "mixed"
    difficulty: str          # "easy" | "moderate" | "hard"
    scenic: bool = Field(default=False)

    # PostGIS LineString, WGS84 (SRID 4326)
    gps_path: str = Field(
        sa_column=Column(Geometry(geometry_type="LINESTRING", srid=4326))
    )

    runs: List["Run"] = Relationship(back_populates="route")
    recommendations: List["Recommendation"] = Relationship(back_populates="route")


# ---------------------------------------------------------------------------
# Run (a completed activity, logged manually or via GPX upload)
# ---------------------------------------------------------------------------

class Run(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    route_id: Optional[UUID] = Field(default=None, foreign_key="route.id")

    run_date: date = Field(index=True)
    distance_km: float
    pace_min_km: float
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    post_run_soreness: Optional[int] = Field(default=None, ge=0, le=10)

    user: User = Relationship(back_populates="runs")
    route: Optional[Route] = Relationship(back_populates="runs")


# ---------------------------------------------------------------------------
# Recommendation (stored output of the scoring engine, for the feedback loop)
# ---------------------------------------------------------------------------

class Recommendation(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    route_id: UUID = Field(foreign_key="route.id")

    rec_date: date = Field(index=True)
    score: float
    reasoning: str            # plain-language explanation shown to the user
    accepted: Optional[bool] = None  # did the user actually run this route

    user: User = Relationship(back_populates="recommendations")
    route: Route = Relationship(back_populates="recommendations")


# ---------------------------------------------------------------------------
# Club / group recommendations
# ---------------------------------------------------------------------------

class Club(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    location: str
    pace_range: str           # e.g. "8:00-9:30 min/mi"
    experience_level: str     # "beginner" | "intermediate" | "advanced" | "all"

    schedules: List["ClubSchedule"] = Relationship(back_populates="club")


class ClubSchedule(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    club_id: UUID = Field(foreign_key="club.id", index=True)

    day_of_week: str          # "monday", "tuesday", ...
    meetup_time: str          # store as string ("18:30") to keep it simple

    club: Club = Relationship(back_populates="schedules")
