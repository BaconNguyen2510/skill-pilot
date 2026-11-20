# Source recovery: preserve the goal when external material is blocked

**Scope:** Host-side workflow for the Skill Pilot v4.0 release blocker ([issue #2](https://github.com/BaconNguyen2510/skill-pilot/issues/2)). This reference is read when source access fails; it is not permission to bypass restrictions. Keep all source retrieval and skill discovery read-only by default.

## Four-step recovery sequence

1. **Goal versus source:** Restate the confirmed user objective internally and keep it unchanged. Record the requested source, its role, the exact observed access status, and what is missing. Example: the goal is to evaluate a short-form video's business idea; the source is a Facebook reel.
2. **Permitted recovery and skill lookup:** Before ending, check relevant already-available public source context (public caption, official transcript, metadata, alternate link provided by the user) only if accessible and allowed. If domain work needs help, search the installed skills by *capability*, not by URL. Example:
   
   ```text
   python <skill-dir>/scripts/skill_scout.py search "video content analysis transcript short-form creative idea evaluation" --harness all --format compact --limit 5
   ```
   
   For Vietnamese input, a corresponding query is `"phân tích nội dung video phụ đề đánh giá ý tưởng"`. Resolve `<skill-dir>` from the containing SKILL.md file; do not literally use the placeholder. Inspect the actual SKILL.md of any promising result and verify the tools are enabled and authorized. Warehouse matches are candidates, **not** proof that a script or plugin is available. A failed lookup or zero matches must be reported truthfully. Do not promote, install or run untrusted scripts solely to fetch a social video.
3. **Use what is grounded:** If an accessible transcript, user-supplied clip, or caption actually contains enough context, continue with the requested evaluation. State which material the analysis is based on; distinguish metadata from video content. If no content is accessible, do not guess what is shown. You can still describe the evaluation framework, such as originality, audience, feasibility, differentiation and execution risk, without pretending to judge the unseen idea.
4. **One precise recovery request:** Ask only for the smallest missing input needed to proceed, such as the video file, caption/transcript, two screenshots, or a short account of the concept. Offer alternatives succinctly, but ask only one focused question and retain the original goal for the next turn. Do not ask "What is your goal?" when the user has already supplied it.

## Error classification and bounded behavior

| Source state | Appropriate behavior | Forbidden claim |
| --- | --- | --- |
| 403 / login-wall / privacy gate | Stop restricted retrieval; discover authorized skills and other user-provided evidence, then request source material | "I watched the reel" or "I bypassed the login" |
| 404 / deleted / wrong URL | If authorized, verify public metadata or alternate user-provided URL; no invented content | "The video says ..." |
| Timeout / rate limit | One bounded retry only if explicitly appropriate; otherwise switch recovery path | "Tried every option" without a trace |
| Host lacks video tool | Read-only capability discovery; if still no tool, request video/caption/transcript | "No relevant skill exists" without checking |
| Transcript provided but clip blocked | Evaluate explicitly from transcript, label missing visual evidence | "I saw the on-screen demonstration" |
| Ambiguous *goal*, not merely inaccessible source | Use the one-question Interview Gate; no speculative plan | Inventing a confirmed objective |

**Important:** Rechecking a public search page is not a substitute for inspecting installed skills when a specialist media/transcription workflow is relevant. Conversely, searching skills is not an excuse to keep retrying a protected website. Stop if permissions or capabilities are unavailable, but continue helping within the evidence you have.

## Example: English, blocked Facebook reel

**Input:** "Look at this reel [Facebook URL]. What do you think of the idea behind it?"

**Expected internal sequence:** goal=assess idea; source=video; web fetch=blocked; check permitted metadata/transcript sources; run or reuse video/media-analysis skill discovery; inspect relevant SKILL.md; record whether any actual content was retrieved.

**Possible user-facing response when still inaccessible:** "Facebook isn't allowing me to view that reel, so I can't evaluate what happens in the video yet. I checked the available ways to analyze its content [describe only checks actually performed]. I can assess originality, target audience, execution feasibility and whether the business model makes sense. Could you share the reel's caption, video, or a short description of the idea so I can evaluate the actual concept?" Do **not** say a tool/skill was checked unless it was.

## Example: Vietnamese

**Input:** "Xem reel này rồi đánh giá ý tưởng kinh doanh bên trong."

**Possible response when still inaccessible:** "Mình chưa xem được nội dung reel vì nguồn đang chặn truy cập, nên chưa thể nhận xét ý tưởng cụ thể. Mình đã kiểm tra các cách/skill có thể dùng [chỉ nêu những bước đã thực sự làm]. Bạn gửi video, caption hoặc mô tả ngắn ý tưởng được không? Mình sẽ đánh giá tính khả thi, khách hàng mục tiêu, điểm khác biệt và rủi ro triển khai."

## Output trace for native-host v4 acceptance

Retain a redacted, source-grounded trace with `original_goal`, `failed_source_role`, `access_observation`, `public_alternatives_checked`, `skill_discovery_observation`, `skill_files_inspected`, `content_actually_seen`, `limitation_disclosure`, `next_source_input`, and `final_response`. Native Codex and Antigravity trial reviewers must check tool logs; self-reported model statements alone do not prove discovery or content access.

No login bypass, unauthorized credential use, independent human-label fabrication, or promise to access every platform is permitted.
