## 2026-09-11 - Batching relationship queries in GET /state
**Learning:** The `GET /state` endpoint previously executed individual `SELECT * FROM relationships WHERE user_id=%s AND girl=%s` queries in a loop for every active resident in the roster (17+ sequential DB connections per state check).
**Action:** Fetch all relationship records for a user at once using `SELECT * FROM relationships WHERE user_id=%s` and map by `girl` slug before iterating through the roster.
