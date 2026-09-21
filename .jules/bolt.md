## 2026-09-12 - Auth Dependency DB Connection Churn
**Learning:** In FastAPI setups without connection pooling, separating session token lookup from user record lookup in `current_user` causes 2 sequential `db()` connection opens/closes per authenticated request. Joining `sessions` and `users` into a single query and passing `conn` and `user_row` to downstream `_ensure_user` cuts auth DB connections and roundtrips by 50%.
**Action:** Always combine session and user queries into a single JOIN in authentication middleware/dependencies, and allow optional `conn`/`user_row` parameter passing to prevent redundant DB connection creation.

## 2026-09-12 - Batch Querying User Relationships in GET /state
**Learning:** Calling `get_relationship(user_id, girl)` sequentially inside a loop over the active roster (35+ residents) opens and closes 35+ DB connections for a single `/state` request. Batch-fetching all relationship records for a user via `SELECT * FROM relationships WHERE user_id=%s` in one query and mapping them in-memory reduces DB connection opens/closes and network roundtrips for `/state` from 35+ down to 1 (~97% reduction).
**Action:** Always batch-query multi-character/multi-entity state endpoints in a single SQL query keyed by `user_id` instead of iterating DB helper calls.
