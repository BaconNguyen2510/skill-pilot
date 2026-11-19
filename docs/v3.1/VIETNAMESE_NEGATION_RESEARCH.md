# Vietnamese Negation & Exclusion-Scope Research (`v3.1` Priority 1)

## 1. Problem Definition
`skills/skill-pilot/scripts/skill_scout.py` must deterministically split Vietnamese and mixed EN/VI queries into positive intent and excluded negation/exclusion clauses while running in pure Python 3.12+ stdlib (zero external pip/JVM dependencies).
- **Observed Failure (`v3.0.0`):** `test_17_vietnamese_tru_negation` (`"chọn công cụ thiết kế trừ figma"`) failed to exclude `figma-design` because `VI_NEGATION_RE` matched `ngoai tru` and `loai tru` but not standalone `trừ` / `trừ ra`.
- **Constraints:** Zero external runtime dependencies, permissive licensing, false-positive protection on Vietnamese homographs (e.g. `trừ` in `phép trừ` / `trừ khi`, `không` in `tại sao không chạy được`, `nó` vs `no`).

## 2. External Candidates Evaluated

| Candidate | URL | License | Runtime Dependencies | Decision |
|---|---|---|---|---|
| **Underthesea** | https://github.com/undertheseanlp/underthesea | **GPL-3.0** | Python + ML/PyTorch (heavy) | **Rejected:** GPL-3.0 copyleft incompatibility; provides tokenization/POS/NER, not exclusion-scope parsing. |
| **VnCoreNLP** | https://github.com/vncorenlp/VnCoreNLP | **MIT** | **Java 8+ JVM** + `.jar` | **Rejected:** Requires JVM runtime; breaks Skill Pilot's pure-Python stdlib CLI constraint. |
| **negspacy (NegEx)** | https://github.com/jeniyat/negspacy | **MIT** | spaCy (`en_*` models) | **Algorithm Adapted:** Rejected spaCy runtime dep, adapted NegEx's pre-negation triggers, pseudo-negation guards, and termination conjunctions into pure Python stdlib. |
| **Host-LLM (`SKILL.md`)** | `skills/skill-pilot/SKILL.md` | N/A | Host LLM session | **Complementary:** Host LLM extracts structured `plan_steps` & `constraints` during interviews; CLI still needs deterministic negation handling for direct `search` & `plan-search`. |

## 3. Selected Design & Benchmark
- **Design:** Extend `_split_query_negations` in `skill_scout.py` using the MIT NegEx pattern:
  - **Unicode-aware Vietnamese exclusion cue:** Match `\btrừ(?:\s+ra)?\b` on the accent-preserved lowercase clause (preventing false positives on accent-stripped homographs like `trụ`/`trù`/`trữ`), plus `tru ra` / `ngoai tru` / `loai tru` / `chu khong phai` / `khong tinh` in `VI_NEGATION_RE`.
  - **Pseudo-negation guards:** Skip `trừ` when preceded by `phép`/`toán` (`phep tru`, `toan tru`) or followed by `khi` (`trừ khi` = "unless").
  - **Termination conjunctions:** Preserve existing `coord_re` (`nhưng`, `nhung`, `chỉ cần`, `but`, `instead`) and punctuation boundaries.
- **Verification Target:** `18/18` in `tests/test_adversarial_auto_eval_v3.py` (removing `@unittest.expectedFailure` from `test_17`) + new Vietnamese exclusion/pseudo-negation/contradiction tests in `tests/test_vietnamese_intent_v31.py`.
