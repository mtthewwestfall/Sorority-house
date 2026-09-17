## 2026-09-12 - Auth Dependency DB Connection Churn
**Learning:** In FastAPI setups without connection pooling, separating session token lookup from user record lookup in `current_user` causes 2 sequential `db()` connection opens/closes per authenticated request. Joining `sessions` and `users` into a single query and passing `conn` and `user_row` to downstream `_ensure_user` cuts auth DB connections and roundtrips by 50%.
**Action:** Always combine session and user queries into a single JOIN in authentication middleware/dependencies, and allow optional `conn`/`user_row` parameter passing to prevent redundant DB connection creation.

## 2026-09-12 - State Endpoint Roster Relationship Query Churn
**Learning:** Iterating over roster doors in GET `/state` and calling `get_relationship()` per door caused an N+1 pattern opening N separate DB connections and executing N+1 queries. Batch querying `SELECT * FROM relationships WHERE user_id=%s` with `get_relationships()` and passing a single `conn` to `roster()` and `get_relationships()` cuts connection opens from N+1 (8) down to 1 and SQL queries from N+1 (8) down to 2 for a 7-resident roster.
**Action:** Pass `conn` down to helper methods in multi-entity endpoints like `/state` and batch query relationship/entity rows in a single SQL query instead of querying per resident in a loop.
