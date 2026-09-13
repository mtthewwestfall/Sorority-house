# Bolt's Journal - Critical Learnings

## 2025-05-18 - Batch Relationship Queries in /state
**Learning:** Calling `get_relationship` inside a loop over resident doors in `/state` caused an N+1 query problem, opening N sequential PostgreSQL TCP/SSL connections (up to 17 connections). Each connection adds network handshake latency.
**Action:** Use `get_relationships_map(user_id, girls)` to batch query all relationship records in a single DB connection and query, reducing DB network overhead by ~94% on state fetches.
