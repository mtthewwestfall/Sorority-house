"""One-time backfill: rename Greek Hollow / Maple Hollow -> God's Greek
in the live personas table.

The seed uses ON CONFLICT DO NOTHING, so rows already in the database keep
whatever branding they were seeded with. This updates the user-visible
blurb and persona text for existing rows without touching anything the
owner edited in the admin console beyond the town name.

Run once against the production DATABASE_URL, then retire.
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("No DATABASE_URL set, skipping migration.")
    exit(0)

REPLACEMENTS = [
    ("Greek Hollow", "God's Greek"),
    ("Maple Hollow", "God's Greek"),
]

try:
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
except Exception as e:
    print(f"Failed to connect to database: {e}")
    exit(0)

try:
    with conn.cursor() as cur:
        cur.execute("SELECT girl, persona, blurb FROM personas")
        rows = cur.fetchall()
        updated = 0
        for row in rows:
            persona = row["persona"] or ""
            blurb = row["blurb"] or ""
            new_persona, new_blurb = persona, blurb
            for old, new in REPLACEMENTS:
                new_persona = new_persona.replace(old, new)
                new_blurb = new_blurb.replace(old, new)
            if new_persona != persona or new_blurb != blurb:
                cur.execute(
                    "UPDATE personas SET persona = %s, blurb = %s WHERE girl = %s",
                    (new_persona, new_blurb, row["girl"]),
                )
                updated += 1
                print(f"Updated branding for {row['girl']}")
    conn.commit()
    print(f"Done. {updated} persona(s) updated.")
except Exception as e:
    print(f"Error during migration: {e}")
finally:
    conn.close()
