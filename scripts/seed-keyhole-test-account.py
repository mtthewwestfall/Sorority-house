"""One-time Keyhole test-account seed.

This file is invoked only by the Railway pre-deploy hook while provisioning the
owner's requested test account. The hook is removed immediately afterward.
"""
import hashlib
import os
import uuid

import psycopg2


EMAIL = "mtthew.westfall@gmail.com"
DISPLAY_NAME = "Matthew Test"
PASSWORD_HASH = (
    "add317c07dbf60f0c253bf2e74c59f73"
    "$c27144711155f1b46c59bc0ceb4e36abfad2bdfacd0676e53fa34872ae0ca855"
)
USER_ID = "u_keyhole_test_mtthew"
SHOW_ID = "test_mtthew_chloe"


def main():
    dsn = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id FROM accounts WHERE email=%s FOR UPDATE",
                (EMAIL,),
            )
            row = cur.fetchone()
            if row:
                user_id = row[0]
                cur.execute(
                    """
                    UPDATE accounts
                       SET password_hash=%s,
                           verified_at=COALESCE(verified_at, now()),
                           verify_token=NULL
                     WHERE email=%s
                    """,
                    (PASSWORD_HASH, EMAIL),
                )
            else:
                user_id = USER_ID
                cur.execute(
                    """
                    INSERT INTO users (user_id, display_name, tier, plan_reset_at)
                    VALUES (%s,%s,'visitor',now() + interval '1 month')
                    ON CONFLICT (user_id) DO UPDATE
                      SET display_name=EXCLUDED.display_name
                    """,
                    (user_id, DISPLAY_NAME),
                )
                cur.execute(
                    """
                    INSERT INTO accounts (email,user_id,password_hash,verified_at)
                    VALUES (%s,%s,%s,now())
                    ON CONFLICT (email) DO UPDATE
                      SET user_id=EXCLUDED.user_id,
                          password_hash=EXCLUDED.password_hash,
                          verified_at=now(),
                          verify_token=NULL
                    """,
                    (EMAIL, user_id, PASSWORD_HASH),
                )

            # Paid-style Keyhole test entitlements; no payment is created or charged.
            cur.execute(
                """
                UPDATE users
                   SET paid_keyhole_purchases=GREATEST(paid_keyhole_purchases,1),
                       webcam_minutes_left=GREATEST(webcam_minutes_left,30),
                       video_replies_left=GREATEST(video_replies_left,70),
                       message_credits=GREATEST(message_credits,100),
                       text_balance=GREATEST(text_balance,100),
                       intro_bought=GREATEST(intro_bought,1),
                       webcam_session_started_at=NULL,
                       webcam_session_duration_s=0
                 WHERE user_id=%s
                """,
                (user_id,),
            )

            # A private READY show for the test account, with a direct entitlement.
            # The admin can start/end it from the existing Keyhole Show Control panel.
            cur.execute(
                """
                INSERT INTO keyhole_shows (
                    show_id,id,show_type,character_id,"character",
                    customer_id,customer,title,description,details,price,
                    status,is_demo,duration_minutes,package
                )
                VALUES (
                    %s,%s,'private','chloe','Chloe',
                    %s,%s,'Keyhole Test Show','Private test show for the owner account',
                    'Test-only private Chloe show',0,'READY',TRUE,30,'standard'
                )
                ON CONFLICT (show_id) DO UPDATE SET
                    customer_id=EXCLUDED.customer_id,
                    customer=EXCLUDED.customer,
                    status='READY',
                    is_demo=TRUE,
                    duration_minutes=30,
                    package='standard',
                    updated_at=now()
                """,
                (SHOW_ID, SHOW_ID, user_id, EMAIL),
            )
            cur.execute(
                """
                INSERT INTO keyhole_entitlements (show_id,user_id,payment_id)
                VALUES (%s,%s,%s)
                ON CONFLICT (show_id,user_id) DO UPDATE
                  SET payment_id=EXCLUDED.payment_id
                """,
                (SHOW_ID, user_id, "test-account-" + SHOW_ID),
            )
        conn.commit()
        print(f"Provisioned {EMAIL} as {user_id}; show={SHOW_ID}", flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
