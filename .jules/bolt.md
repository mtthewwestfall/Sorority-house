## 2026-09-12 - Auth Dependency DB Connection Churn
**Learning:** In FastAPI setups without connection pooling, separating session token lookup from user record lookup in `current_user` causes 2 sequential `db()` connection opens/closes per authenticated request. Joining `sessions` and `users` into a single query and passing `conn` and `user_row` to downstream `_ensure_user` cuts auth DB connections and roundtrips by 50%.
**Action:** Always combine session and user queries into a single JOIN in authentication middleware/dependencies, and allow optional `conn`/`user_row` parameter passing to prevent redundant DB connection creation.

## 2026-09-18 - Endpoint N+1 DB Query Churn on Roster Loops
**Learning:** Iterating through roster items (~35 items) and fetching individual relationship rows (`get_relationship`) inside endpoint handlers like `GET /state` creates an N+1 query problem, opening 35+ DB connections per request. Batching relationship retrieval into a single `SELECT * FROM relationships WHERE user_id=%s` query reduces DB connections and round-trips from N to 1 (~97% reduction).
**Action:** When endpoint handlers iterate over list items (like roster/house residents), fetch user-scoped relational state in a single batch query prior to the loop.
