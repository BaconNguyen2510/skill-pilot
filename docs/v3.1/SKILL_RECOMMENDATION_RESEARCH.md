# Skill Recommendation Quality & Capability-Evidence Research (`v3.1` Priority 2)

## 1. Problem Definition
1. **Verifiable Capability Evidence:** `session_planner.py` previously accepted any non-empty `capability_evidence` string for `direct` coverage without checking whether the cited capability actually exists in the matched `SKILL.md` on disk.
2. **Ranking vs. Functional Coverage:** Retrieval scores (`score`) only measure lexical/alias overlap, not whether a skill can perform the task. `direct`, `partial`, `none`, and `unverified_fit` must remain strictly separated.
3. **Vietnamese Retrieval Gap:** Dev `vi` MRR@5 is `1.0` (`recall@5 = 0.9074`, `forbidden_hit_rate@5 = 0.10`), while holdout `vi` MRR@5 is `0.6818` (`recall@5 = 0.6364`) because pure lexical matching cannot bridge unseen Vietnamese phrasing to English `SKILL.md` descriptions.

## 2. Approaches Compared

| Approach | License / Source | Dependencies | Trade-off & Decision |
|---|---|---|---|
| **Multilingual Dense Embeddings (`BAAI/bge-m3` / `sentence-transformers`)** | MIT / Apache-2.0 | PyTorch + GB model weights | **Rejected for CLI:** Violates pure-Python 3.12+ stdlib constraint and `<15ms` latency (`p95 = 13.1ms`). |
| **`dorianbrown/rank_bm25` + Reciprocal Rank Fusion (RRF)** | Apache-2.0 (`https://github.com/dorianbrown/rank_bm25`) | `rank-bm25` / `numpy` | **Pattern Noted:** RRF (`1/(k+rank)`) is ideal for hybrid fusion, but does not bridge cross-lingual EN/VI vocabulary without bilingual expansion or embeddings. |
| **Disk-Grounded `SKILL.md` Capability Extraction + Evidence Verification** | Pure Python stdlib | None | **Selected:** Extracts real headings/descriptions from matched `SKILL.md` files on disk and rejects `direct` claims whose `capability_evidence` is ungrounded or title-only (`downgraded to unverified_fit`). |

## 3. Acceptance Criteria
- `direct` coverage is rejected (`unverified_fit`) unless `capability_evidence` is verified against the actual `SKILL.md` content on disk (beyond just the skill `id`/`name`).
- `partial` coverage requires explicit `uncovered_capabilities`.
- Zero regression on exclusion safety, `165+` unit tests, and holdout benchmark.
