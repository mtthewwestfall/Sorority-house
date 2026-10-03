## 2026-09-12 - Auth Dependency DB Connection Churn
**Learning:** In FastAPI setups without connection pooling, separating session token lookup from user record lookup in `current_user` causes 2 sequential `db()` connection opens/closes per authenticated request. Joining `sessions` and `users` into a single query and passing `conn` and `user_row` to downstream `_ensure_user` cuts auth DB connections and roundtrips by 50%.
**Action:** Always combine session and user queries into a single JOIN in authentication middleware/dependencies, and allow optional `conn`/`user_row` parameter passing to prevent redundant DB connection creation.

## 2026-09-12 - Batch Querying User Relationships in GET /state
**Learning:** Calling `get_relationship(user_id, girl)` sequentially inside a loop over the active roster (35+ residents) opens and closes 35+ DB connections for a single `/state` request. Batch-fetching all relationship records for a user via `SELECT * FROM relationships WHERE user_id=%s` in one query and mapping them in-memory reduces DB connection opens/closes and network roundtrips for `/state` from 35+ down to 1 (~97% reduction).
**Action:** Always batch-query multi-character/multi-entity state endpoints in a single SQL query keyed by `user_id` instead of iterating DB helper calls.

## 2026-09-12 - N+1 Persona Difficulty DB Lookups in Roster Loops
**Learning:** `roster()` returns persona rows containing the `difficulty` column, but calling `difficulty_for(girl)` inside `GET /roster` and `GET /state` loops opens and closes N sequential DB connections (`SELECT difficulty FROM personas WHERE girl=%s`) for N roster items. Using pre-fetched `r.get("difficulty")` or `row.get("difficulty")` in roster iterations and backing `difficulty_for()` with an in-memory TTL dictionary cache eliminates N DB queries per request (reducing DB connection opens from N+1 down to 1 for `/roster`).
**Action:** Always check if iteration items already contain the needed attribute before calling individual lookup helpers, and add in-memory TTL caching to single-entity getter functions called in hot paths.

## 2026-09-12 - Batch Querying `house_rules` SQL Lookups in Character References
**Learning:** `get_character_references(character_id)` made 3 sequential calls to `_get_house_rule()` (`ref_master_{cid}`, `ref_appearance_{cid}`, `ref_private_{cid}`), opening and closing 3 separate PostgreSQL connections per character reference call. Batching the keys into a single `SELECT key, value FROM house_rules WHERE key = ANY(%s)` query reduces DB connection opens/closes and network roundtrips from 3 down to 1 (a 66.7% reduction).
**Action:** Whenever retrieving multiple config or reference keys from `house_rules` or similar key-value DB tables, use a batch helper `_get_house_rules(keys)` with `WHERE key = ANY(%s)` instead of making sequential single-key lookup calls.
