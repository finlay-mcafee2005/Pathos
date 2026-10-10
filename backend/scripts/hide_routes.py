"""
Hide routes that shouldn't be recommended: not really runnable (a tourist
sidewalk, a planned path that doesn't exist yet, abandoned or motorbike
trails) or a duplicate of another route. Hidden routes stay in the database,
so runs and favorites linked to them keep working; they just never show up
as recommendations.

Run from backend/:
    python3 scripts/hide_routes.py --dry-run    # list what would be hidden
    python3 scripts/hide_routes.py              # hide them
    python3 scripts/hide_routes.py --unhide "Hollywood Walk of Fame"   # undo one
"""

import os
import sys

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:devpassword@localhost:5432/run_recommender")

# (SQL LIKE pattern on the route's name, why it's hidden)
HIDE = [
    ("%Walk of Fame%",           "tourist sidewalk, not a running route"),
    ("Future %",                 "planned path that doesn't exist yet"),
    ("%Abandoned%",              "abandoned"),
    ("%abandoned segment%",      "abandoned segment"),
    ("%Motorbike%",              "motorbike trail"),
    ("Natures Canteen Trail",    "duplicate of Nature's Canteen Trail"),
]


def main():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE route ADD COLUMN IF NOT EXISTS hidden BOOLEAN DEFAULT FALSE"))

        if "--unhide" in sys.argv:
            name = sys.argv[sys.argv.index("--unhide") + 1]
            n = conn.execute(text("UPDATE route SET hidden = FALSE WHERE name = :n OR nickname = :n"),
                             {"n": name}).rowcount
            print(f"Unhid {n} route(s) named {name!r}.")
            return

        dry = "--dry-run" in sys.argv
        total = 0
        for pattern, why in HIDE:
            rows = conn.execute(text(
                "SELECT id, COALESCE(nickname, name) FROM route "
                "WHERE (name ILIKE :p OR nickname ILIKE :p) AND NOT COALESCE(hidden, FALSE)"),
                {"p": pattern}).all()
            for _id, title in rows:
                print(f"  {'would hide' if dry else 'hiding'}: {title}  ({why})")
            if rows and not dry:
                conn.execute(text("UPDATE route SET hidden = TRUE WHERE id = ANY(:ids)"),
                             {"ids": [r[0] for r in rows]})
            total += len(rows)
        if dry:
            print(f"\nDry run: {total} route(s) would be hidden. Run without --dry-run to hide them.")
        else:
            print(f"\nHid {total} route(s).")


if __name__ == "__main__":
    main()
