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
from sqlalchemy import Column, UniqueConstraint


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class User(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    full_name: str
    email: str = Field(unique=True, index=True)
    phone_number: Optional[str] = None
    date_of_birth: Optional[date] = None
    hashed_password: str

    fitness_level: str = Field(default="beginner")
    weekly_mileage_avg: float = Field(default=0.0)
    usual_pace_min_km: Optional[float] = None   # easy-run pace from signup (min per km)
    email_verified: bool = Field(default=False)
    email_verified_at: Optional[datetime] = None

    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    goal: str = Field(default="general_fitness")
    club_id: Optional[UUID] = Field(default=None, foreign_key="club.id")

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
    energy_score: int = Field(ge=0, le=10)  # 0 = low mental energy, 10 = high

    sleep_hours: Optional[float] = None
    sleep_quality: Optional[int] = Field(default=None, ge=1, le=5)  # 1 = poor, 5 = great

    sore_body_parts: str = Field(default="[]")  # JSON-encoded list of strings
    planned_distance_km: Optional[float] = None
    wants_adventure: bool = Field(default=False)
    wants_scenic: bool = Field(default=False)
    surface_preference: Optional[str] = None  # "trail" | "road" | None = no preference
    mood_note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    willing_to_drive_km: Optional[float] = None
    run_time: Optional[str] = None             # "now" | "morning" | "midday" | "evening"
    available_minutes: Optional[float] = None
    mood: Optional[str] = None                 # "stressed" | "flat" | "good" | "restless" | "low"
    run_intent: Optional[str] = None           # "easy" | "workout" | "long" | "explore"
    hills_pref: Optional[str] = None           # "avoid" | "want" | None

    user: User = Relationship(back_populates="checkins")
# ---------------------------------------------------------------------------
# Route (the thing being recommended)
# ---------------------------------------------------------------------------

class Route(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    nickname: Optional[str] = None   # unique, descriptive title shown in the app (scripts/name_routes.py)
    hidden: Optional[bool] = Field(default=False)   # True = never recommended (not runnable / duplicate)

    distance_km: float
    elevation_gain_m: float
    elevation_loss_m: Optional[float] = None   # total descent along the stored path
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
    # filled in when imported from a watch file
    duration_s: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    avg_heart_rate: Optional[float] = None
    max_heart_rate: Optional[float] = None
    source: Optional[str] = None          # "manual" | "gpx" | "tcx" | "fit" | "follow"
    # research: which recommendation this run came from, and did it fit
    recommendation_id: Optional[UUID] = None
    pick_fit: Optional[str] = None        # "yes" | "sort_of" | "no"

    user: User = Relationship(back_populates="runs")
    route: Optional[Route] = Relationship(back_populates="runs")


# ---------------------------------------------------------------------------
# Recommendation (stored output of the scoring engine, for the feedback loop)
# ---------------------------------------------------------------------------

class Recommendation(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    route_id: Optional[UUID] = Field(default=None, foreign_key="route.id")   # None for combined routes

    rec_date: date = Field(index=True)
    score: float
    reasoning: str            # plain-language explanation shown to the user
    accepted: Optional[bool] = None  # did the user actually run this route
    # research logging: which check-in produced it, where it ranked, what came of it
    checkin_id: Optional[UUID] = Field(default=None, foreign_key="checkin.id", index=True)
    rank: Optional[int] = None
    route_name: Optional[str] = None
    shown_at: Optional[datetime] = None
    run_id: Optional[UUID] = None

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
    join_code: Optional[str] = Field(default=None, unique=True, index=True)
    latitude: Optional[float] = None      # where the group usually meets
    longitude: Optional[float] = None
    source_url: Optional[str] = None      # where the schedule came from
    verified_on: Optional[date] = None    # when we last checked it
    notes: Optional[str] = None           # caveats (fees, varying times, ...)

    schedules: List["ClubSchedule"] = Relationship(back_populates="club")

class ClubSchedule(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    club_id: UUID = Field(foreign_key="club.id", index=True)

    day_of_week: str          # "monday", "tuesday", ...
    meetup_time: str          # store as string ("18:30") to keep it simple
    distance_mi: Optional[float] = None   # typical distance for this session
    run_type: Optional[str] = None        # "easy" | "long" | "workout" | "social"
    surface: Optional[str] = None         # "road" | "trail" | "mixed"

    club: Club = Relationship(back_populates="schedules")


# ---------------------------------------------------------------------------
# FavoriteRoute (routes a user has saved from their recommendations)
# ---------------------------------------------------------------------------

class FavoriteRoute(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("user_id", "route_id", name="uq_favorite_user_route"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    route_id: UUID = Field(foreign_key="route.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)



# ---------------------------------------------------------------------------
# Run together: a few friends who check in separately and get one shared pick
# ---------------------------------------------------------------------------

class RunGroup(SQLModel, table=True):
    __tablename__ = "run_group"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    join_code: str = Field(index=True, unique=True)
    owner_id: UUID = Field(foreign_key="user.id")
    # optional meeting spot; when empty, routes start somewhere fair for everyone's home
    meet_label: Optional[str] = None
    meet_lat: Optional[float] = None
    meet_lon: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RunGroupMember(SQLModel, table=True):
    __tablename__ = "run_group_member"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_run_group_member"),)
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    group_id: UUID = Field(foreign_key="run_group.id", index=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    joined_at: datetime = Field(default_factory=datetime.utcnow)
