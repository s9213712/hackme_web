# 2026-05-15 Documentation Deployment Audit

## Findings

- No active broken Markdown links remain.
- No active orphan Markdown files remain when starting from `README.md`, `docs/README.md`, and `docs/00_START_HERE.md`.
- No active non-archive docs still use `contract` / `契約` wording. Archived historical reports may still preserve original wording.
- No exact duplicate Markdown file groups remain.

## Changes Made

- Added deployment reading rules to `docs/README.md`, `docs/README.zh-TW.md`, and `docs/02_DEPLOY_PRODUCTION.md`.
- Linked `docs/AGENTS/research/README.md` from the main documentation map and converted research priority items into real Markdown links.
- Fixed broken relative links in PointsChain v2 research docs and `archive/history/VERSION_STORY.md`.
- Reworded active docs from legal-sounding `contract` language to behavior/spec/shape/rule/requirements wording.
- Clarified trading background engine status:
  - base worker, job/lease/run tables, and root status/pause/resume/run-once APIs are implemented
  - sitewide snapshot reports and full lending-pool drilldowns are still staged
- Added implemented trading background APIs to `API_REFERENCE.md`.
- Moved `FINAL_CODE_REVIEW_2026-05-14.md` into `docs/archive/` and indexed it as historical review evidence.
- Replaced three duplicated archived chess pipeline files with short pointer pages to the canonical `pvp_pipeline/` copies.

## Verification

- Markdown relative link scan: `broken_count 0`.
- Reachability scan: `active_unreachable_count 0`, `reachable_docs 216 of 357`.
- Wording scan: `active_contract_word_hits 0`.
- Exact duplicate scan: `exact_duplicate_groups 0`.

## Deployment Notes

- Use numbered guides, domain `README.md`, `API_REFERENCE.md`, and `SYSTEM_DEPENDENCIES.md` for deployment decisions.
- Treat `archive/`, `evidence/`, and one-off reports as historical evidence.
- Treat `AGENTS/research/` as future-work specification unless the same feature is also described as implemented in the operator docs.
- Trading background worker base functionality is no longer just a proposal, but full sitewide root reporting still needs snapshot-backed implementation before production operation.
