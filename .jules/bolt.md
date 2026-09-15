## 2025-02-23 - Batch relationships fetch to fix N+1 in /state
**Learning:** The `/state` endpoint iterates over all house personas (up to 17 residents) and fetched each relationship individually via `get_relationship()`. Because `get_relationship()` opens and closes a DB connection per call, this caused 17+ sequential DB round-trips per GET `/state` request.
**Action:** Batch fetch all user relationships using `get_relationships(user_id)` prior to looping through roster doors.
