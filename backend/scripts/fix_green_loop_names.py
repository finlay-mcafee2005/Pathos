"""
Some "Green Loops" (mostly downtown) turned out not to be green: the generator
counted sidewalks as paths. Their scenic share measured under 25%, so drop
"Green" from those titles ("Jewelry District Green Loop" -> "Jewelry District Loop").

    DATABASE_URL=... python3 scripts/fix_green_loop_names.py --dry-run
    DATABASE_URL=... python3 scripts/fix_green_loop_names.py
"""
import os
import sys

from sqlalchemy import create_engine, text

if "DATABASE_URL" not in os.environ:
    sys.exit('DATABASE_URL isn\'t set. Run: export DATABASE_URL="<your Supabase link>"')
engine = create_engine(os.environ["DATABASE_URL"])
with engine.begin() as conn:
    taken = {r[0] for r in conn.execute(text("SELECT COALESCE(nickname, name) FROM route"))}
    rows = conn.execute(text("SELECT id, COALESCE(nickname, name) FROM route "
                             "WHERE COALESCE(nickname, name) LIKE '%Green Loop%' "
                             "AND COALESCE(scenic_pct, 0) < 0.25")).all()
    changes = []
    for rid, title in rows:
        new = title.replace(" Green Loop", " Loop")
        base, n = new, 2
        while new in taken:
            new = f"{base} #{n}"
            n += 1
        taken.add(new)
        changes.append((rid, title, new))
    for _, old, new in changes[:15]:
        print(f"  {old}  ->  {new}")
    print(f"{len(changes)} titles to fix.")
    if "--dry-run" in sys.argv or not changes:
        print("Dry run: nothing saved." if changes else "Nothing to do.")
        raise SystemExit
    conn.execute(text("UPDATE route SET name = :n, nickname = :n WHERE id = :id"),
                 [{"id": rid, "n": new} for rid, _, new in changes])
    print("Saved.")
