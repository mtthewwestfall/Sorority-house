import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("No DATABASE_URL set, skipping migration since we must be running locally with an empty DB.")
    exit(0)

# Connect to database
try:
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
except Exception as e:
    print(f"Failed to connect to database: {e}")
    exit(0)

# Updates
try:
    with conn.cursor() as cur:
        # Fetch all personas
        cur.execute("SELECT girl, persona, blurb FROM personas")
        rows = cur.fetchall()
        for row in rows:
            persona = row["persona"]
            blurb = row["blurb"]
            changed = False

            # Simple replacements for "house" and "sorority" in persona and blurb
            # Ensure case insensitivity or cover likely variations.

            new_persona = persona.replace("sorority house", "Maple Hollow")
            new_persona = new_persona.replace("Sorority House", "Maple Hollow")
            new_persona = new_persona.replace("sorority", "town")
            new_persona = new_persona.replace("Sorority", "Town")
            new_persona = new_persona.replace("social chair of the house", "social host of the town")
            new_persona = new_persona.replace("the house", "the town")
            new_persona = new_persona.replace("Slowest in the house by design", "Slowest in town by design")
            new_persona = new_persona.replace("in the house", "in town")
            new_persona = new_persona.replace("the house.", "the town.")

            new_blurb = blurb.replace("sorority house", "Maple Hollow")
            new_blurb = new_blurb.replace("Sorority House", "Maple Hollow")
            new_blurb = new_blurb.replace("sorority", "town")
            new_blurb = new_blurb.replace("Sorority", "Town")
            new_blurb = new_blurb.replace("social chair of the house", "social host of the town")
            new_blurb = new_blurb.replace("the house", "the town")
            new_blurb = new_blurb.replace("Slowest in the house by design", "Slowest in town by design")
            new_blurb = new_blurb.replace("in the house", "in town")
            new_blurb = new_blurb.replace("the house.", "the town.")

            if new_persona != persona or new_blurb != blurb:
                cur.execute(
                    "UPDATE personas SET persona = %s, blurb = %s WHERE girl = %s",
                    (new_persona, new_blurb, row["girl"])
                )
                print(f"Updated persona for {row['girl']}")

    conn.commit()
    print("Database migration completed successfully.")
except Exception as e:
    print(f"Error during migration: {e}")
finally:
    conn.close()
