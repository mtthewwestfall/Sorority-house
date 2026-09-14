## 2026-05-17 - Chat Log Message Count Index Optimization
**Learning:** `picture_status()` and user details lookups count messages with `WHERE user_id=%s AND sender='user'`. The existing index `idx_chat_user_girl` on `(user_id, girl, id)` required sequential filtering or composite index scans when `girl` was not specified, slowing down picture status checks on image generation and status endpoints.
**Action:** When querying `chat_logs` for user-wide metrics (such as message counts across all residents), ensure an index exists on `(user_id, sender)` to allow fast index-only scans.
