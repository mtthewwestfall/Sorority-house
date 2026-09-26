import os
import psycopg2

EMAIL = "mtthew.westfall@gmail.com"

conn = psycopg2.connect(os.environ["DATABASE_URL"])
try:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET webcam_minutes_left = GREATEST(COALESCE(webcam_minutes_left, 0), %s) "
            "FROM accounts a WHERE users.user_id = a.user_id AND lower(a.email)=lower(%s) "
            "RETURNING users.user_id, users.webcam_minutes_left",
            (1000, EMAIL),
        )
        row = cur.fetchone()
        if not row:
            raise SystemExit("TEST_GRANT_FAILED: existing account not found")
        conn.commit()
        print(f"TEST_GRANT_OK user_id={row[0]} webcam_minutes_left={row[1]}")
finally:
    conn.close()
