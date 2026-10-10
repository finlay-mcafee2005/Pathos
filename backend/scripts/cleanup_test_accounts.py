"""
Wipe practice/participant test accounts and everything linked to them, so
each interview starts from a clean slate. Only touches accounts whose email
matches the pattern (default: anything @pathos.test). Real accounts are
never touched.

Run from backend/:
    python3 scripts/cleanup_test_accounts.py                  # list what would be deleted
    python3 scripts/cleanup_test_accounts.py --yes            # delete it
    python3 scripts/cleanup_test_accounts.py --email p3@pathos.test --yes   # just one account
    python3 scripts/cleanup_test_accounts.py --pattern "%@test.com" --yes   # a different pattern

Give interview participants emails like p1@pathos.test, p2@pathos.test, ...
"""

import os
import sys

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:devpassword@localhost:5432/run_recommender")


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    pattern = arg("--pattern", "%@pathos.test")
    email = arg("--email")
    if email and not email.endswith("@pathos.test") and "--force" not in sys.argv:
        sys.exit(f"Refusing to delete {email}: not a @pathos.test account (add --force if you're sure).")

    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        if email:
            users = conn.execute(text('SELECT id, email, full_name FROM "user" WHERE lower(email) = lower(:e)'),
                                 {"e": email}).all()
        else:
            users = conn.execute(text('SELECT id, email, full_name FROM "user" WHERE email ILIKE :p ORDER BY email'),
                                 {"p": pattern}).all()
        if not users:
            print("No matching test accounts. Nothing to do.")
            return

        ids = [u[0] for u in users]
        counts = {}
        for table in ("checkin", "run", "recommendation", "injury", "favoriteroute", "run_group_member"):
            counts[table] = conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE user_id = ANY(:ids)"),
                                         {"ids": ids}).scalar()

        print(f"{len(users)} test account(s):")
        for _id, em, name in users:
            print(f"  {em}  ({name})")
        print("Linked data: " + ", ".join(f"{n} {t}" for t, n in counts.items() if n) if any(counts.values())
              else "No linked data.")

        if "--yes" not in sys.argv:
            print("\nNothing deleted. Run again with --yes to delete these accounts and their data.")
            return

        p = {"ids": ids}
        # children first, so foreign keys don't block the delete
        conn.execute(text("DELETE FROM recommendation WHERE user_id = ANY(:ids)"), p)
        conn.execute(text("DELETE FROM run WHERE user_id = ANY(:ids)"), p)
        conn.execute(text("DELETE FROM checkin WHERE user_id = ANY(:ids)"), p)
        conn.execute(text("DELETE FROM injury WHERE user_id = ANY(:ids)"), p)
        conn.execute(text("DELETE FROM favoriteroute WHERE user_id = ANY(:ids)"), p)
        conn.execute(text("DELETE FROM run_group_member WHERE user_id = ANY(:ids)"), p)
        # groups a test account created: hand them to a remaining member, or remove them if empty
        for (gid,) in conn.execute(text("SELECT id FROM run_group WHERE owner_id = ANY(:ids)"), p).all():
            heir = conn.execute(text("SELECT user_id FROM run_group_member WHERE group_id = :g ORDER BY joined_at LIMIT 1"),
                                {"g": gid}).scalar()
            if heir:
                conn.execute(text("UPDATE run_group SET owner_id = :u WHERE id = :g"), {"u": heir, "g": gid})
            else:
                conn.execute(text("DELETE FROM run_group WHERE id = :g"), {"g": gid})
        conn.execute(text('DELETE FROM "user" WHERE id = ANY(:ids)'), p)
        print(f"\nDeleted {len(users)} test account(s) and their data.")


if __name__ == "__main__":
    main()
