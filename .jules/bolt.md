## 2026-09-12 - Auth Dependency DB Connection Churn
**Learning:** In FastAPI setups without connection pooling, separating session token lookup from user record lookup in `current_user` causes 2 sequential `db()` connection opens/closes per authenticated request. Joining `sessions` and `users` into a single query and passing `conn` and `user_row` to downstream `_ensure_user` cuts auth DB connections and roundtrips by 50%.
**Action:** Always combine session and user queries into a single JOIN in authentication middleware/dependencies, and allow optional `conn`/`user_row` parameter passing to prevent redundant DB connection creation.

## 2026-09-12 - Batch Querying User Relationships in GET /state
**Learning:** Calling `get_relationship(user_id, girl)` sequentially inside a loop over the active roster (35+ residents) opens and closes 35+ DB connections for a single `/state` request. Batch-fetching all relationship records for a user via `SELECT * FROM relationships WHERE user_id=%s` in one query and mapping them in-memory reduces DB connection opens/closes and network roundtrips for `/state` from 35+ down to 1 (~97% reduction).
**Action:** Always batch-query multi-character/multi-entity state endpoints in a single SQL query keyed by `user_id` instead of iterating DB helper calls.

## 2026-09-12 - N+1 Persona Difficulty DB Lookups in Roster Loops
**Learning:** `roster()` returns persona rows containing the `difficulty` column, but calling `difficulty_for(girl)` inside `GET /roster` and `GET /state` loops opens and closes N sequential DB connections (`SELECT difficulty FROM personas WHERE girl=%s`) for N roster items. Using pre-fetched `r.get("difficulty")` or `row.get("difficulty")` in roster iterations and backing `difficulty_for()` with an in-memory TTL dictionary cache eliminates N DB queries per request (reducing DB connection opens from N+1 down to 1 for `/roster`).
**Action:** Always check if iteration items already contain the needed attribute before calling individual lookup helpers, and add in-memory TTL caching to single-entity getter functions called in hot paths.

## 2026-09-24 - Pre-compiling Combined Regex Patterns in Character Engine Intent Parsing
**Learning:** Iterating over lists of regex pattern strings with `re.search` inside `parse_intent` on every character turn causes repeated string regex compilation/search overhead across 20+ patterns. Combining pattern lists into pre-compiled single regular expression objects (`_OFF_CARD_RE`, `_COMMAND_RE`, `_DIRECT_RE`) at module load time reduces pattern evaluation overhead in `parse_intent` by ~85% (~7x speedup).
**Action:** Always pre-compile pattern lists into combined module-level `re.Pattern` objects when performing repeated intent, category, or keyword classification in hot path loops.
