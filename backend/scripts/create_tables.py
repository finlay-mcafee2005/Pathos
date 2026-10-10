"""
One-off script: creates all tables defined in app/models.py
against your local Postgres+PostGIS container.

Run with: python3 scripts/create_tables.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlmodel import SQLModel, create_engine
from app.models import *  # noqa: F401,F403  (imports all table classes)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:devpassword@localhost:5432/run_recommender")

engine = create_engine(DATABASE_URL, echo=True)

SQLModel.metadata.create_all(engine)

print("Tables created successfully.")