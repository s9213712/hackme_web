# Scripts Index

This is the registration table for maintained operator, QA, security, and gate
scripts.

## Governance Rules

- Every new QA, security, pentest, stress, smoke, or production-gate script must
  be registered here in the same change that adds the script.
- Every script that can be called by the production gate must include owner,
  purpose, artifact, and failure meaning.
- Thin wrappers and symlinks must be registered as wrappers and point to their
  implementation path.
- One-off experiments do not belong in `scripts/`. Move them outside the repo or
  promote them into a maintained entry with an owner and artifact contract.
- Focused regression checks are not full validation and must not be labeled as
  full validation in docs, reports, PR descriptions, or script output.
- User-facing scripts must print progress by default: target/runtime, phase
  start, phase result, artifact path, and failure hint. Machine-readable
  `--json` modes may suppress progress text.

## Production Gate Usable Scripts

| Report type | Entry | Owner | Purpose | Artifact | Failure meaning |
|---|---|---|---|---|---|
| `clean_smoke` | `scripts/on_live_reports/clean_smoke.py` -> `scripts/security/server_mode/server_mode_v2_clean_smoke.py` | Server Mode / Security | Verify clean Server Mode v2 baseline behavior. | `runtime/reports/security/production_gate/clean_smoke_*` | Baseline server-mode behavior is unsafe or inconsistent; do not unlock production. |
| `adversarial` | `scripts/on_live_reports/adversarial.py` -> `scripts/security/server_mode/server_mode_v2_adversarial.py` | Server Mode / Security | Exercise adversarial mode, log, tester-token, shadow, and gate boundaries. | `runtime/reports/security/production_gate/adversarial_*` | A bypass or tamper path may exist; production gate must fail closed. |
| `redteam_l2` | `scripts/on_live_reports/redteam_l2.py` -> `scripts/security/server_mode/server_mode_v2_redteam_l2.py` | Server Mode / Security | Run level-2 replay, revocation, lockdown, fake-report, and integrity tamper checks. | `runtime/reports/security/production_gate/redteam_l2_*` | A higher-risk security invariant regressed; do not treat other green checks as sufficient. |
| `log_chain_verify` | `scripts/on_live_reports/log_chain_verify.py` | Audit / Security | Verify audit log hash-chain continuity and tamper evidence. | `runtime/reports/security/production_gate/log_chain_verify_*` | Audit evidence cannot be trusted for this target commit. |
| `integrity_guard` | `scripts/on_live_reports/integrity_guard.py` | Integrity / Security | Check integrity guard status and pending findings. | `runtime/reports/security/production_gate/integrity_guard_*` | Filesystem or manifest integrity is unknown or compromised. |
| `cloud_drive_quota_permission` | `scripts/on_live_reports/cloud_drive_quota_permission.py` | Storage / Security | Validate cloud-drive quota and permission boundaries. | `runtime/reports/security/production_gate/cloud_drive_quota_permission_*` | Storage isolation or quota enforcement may leak across users. |
| `stress` | `scripts/on_live_reports/stress.py` -> `scripts/security/pentest/trading_stress_pentest.py` plus production-gate direct stress drivers | Trading / Reliability | Validate trading stress and gate-level stress/reliability behavior. | `runtime/reports/security/stress_*`, `runtime/reports/security/trading_stress_report_*` | Runtime or trading reliability/correctness cannot be trusted under load. |
| `permission` | `scripts/on_live_reports/permission.py` -> `scripts/security/pentest/functional_permission_pentest.py` | RBAC / Security | Verify role, permission, and privilege-abuse matrix. | `runtime/reports/security/functional_permission_pentest_*` | A user role can do something it should not, or a valid role is blocked unexpectedly. |
| `functional` | `scripts/on_live_reports/functional.py` -> `scripts/security/pentest/run_functional_smoke.sh --core-only` + `tests/security/smoke/smoke_suite.py` | Core / Security | Run isolated runtime core functional smoke for production-gate evidence; broad product QA stays in `run_functional_smoke.sh --qa-full`. | `runtime/reports/security/functional_<RUN_ID>/` | A core auth/admin/user/points/trading/security workflow regressed; this is still not a full production validation by itself. |
| `pentest` | `scripts/on_live_reports/pentest.py` -> `scripts/security/pentest/session_security_pentest.py`; gate also calls `scripts/security/pentest/run_pentest.sh` | Security | Run session/security pentest and external scanner orchestration. | `runtime/reports/security/<RUN_ID>/` | Web/session/security posture is not acceptable for promotion. |
| `snapshot_restore` | `scripts/on_live_reports/snapshot_restore.py` | Snapshot / Server Mode | Validate snapshot, restore, reset, and runtime cleanup behavior. | `runtime/reports/security/production_gate/snapshot_restore_*` | Recovery boundaries are not reliable; production rollback cannot be trusted. |
| `pytest` | `scripts/on_live_reports/pytest.py` and `scripts/testing/pytest_in_tmp.sh` | QA | Run the selected pytest suite in an isolated copy. | `runtime/reports/security/production_gate/pytest_*` or pytest output captured by the caller | Unit/integration regression exists in the selected suite; scope depends on selected tests. |
| `points_chain_consistency` | `scripts/on_live_reports/points_chain_consistency.py` | PointsChain / Ledger | Validate wallet, ledger, hash-chain, and consistency invariants. | `runtime/reports/security/production_gate/points_chain_consistency_*` | Ledger/economy state cannot be trusted. |
| `on_live_reports_make` | `scripts/on_live_reports/on_live_reports_make.py` -> `scripts/security/gate/on_live_reports_make.py` | Release / Security | Orchestrate and verify the production gate report set. | `runtime/reports/security/production_gate/on_live_reports_make_*` | Gate evidence is missing, stale, fake, or failed; production unlock must be blocked. |

## Direct QA And Security Entrypoints

| Path | Type | Owner | Purpose | Artifact | Failure meaning |
|---|---|---|---|---|---|
| `scripts/security/pentest/run_functional_smoke.sh --qa-full` | Functional smoke | QA / Product Areas | Start an isolated runtime and exercise broad product workflows including community/chat/storage/video/ComfyUI/reports/moderation. | `runtime/reports/security/functional_<RUN_ID>/` | A broad user/admin/product workflow failed, or runtime cleanup/restart invariants failed. |
| `scripts/security/pentest/run_pentest.sh` | Pentest orchestrator | Security | Run built-in and optional external security checks by check ID. | `runtime/reports/security/<RUN_ID>/` | At least one selected security check failed; inspect the per-check raw output. |
| `scripts/security/pentest/functional_permission_pentest.py` | Permission pentest | RBAC / Security | Exercise anonymous/user/manager/root access boundaries. | `runtime/reports/security/functional_permission_pentest_*` | Permission matrix regressed or test credentials are invalid. |
| `scripts/security/pentest/session_security_pentest.py` | Session pentest | Auth / Security | Validate session, CSRF, and auth hardening behavior. | Called report path or caller raw output | Session/auth security invariant failed. |
| `scripts/security/pentest/stress_test.py` | HTTP stress | Reliability | Run generic HTTP stress against an owned target. | `runtime/reports/security/stress_*` | Target failed under configured load or returned unacceptable error rates. |
| `scripts/security/pentest/trading_stress_pentest.py` | Trading stress/correctness | Trading / Reliability | Validate trading correctness, stress, restore, and numeric invariants. | `runtime/reports/security/trading_stress_report_*` | Trading state, pricing, restore, or risk gates regressed. |
| `scripts/security/pentest/video_module_pentest.py` | Video security smoke | Video / Security | Validate video sharing, access, and E2EE envelope boundaries. | Caller report path or raw output | Video access control or share isolation regressed. |
| `scripts/security/gate/on_live_reports_make.py` | Production-gate orchestrator | Release / Security | Generate and verify live production-gate evidence. | `runtime/reports/security/production_gate/on_live_reports_make_*` | Gate evidence cannot unlock production. |
| `scripts/security/gate/whole_site_production_gate.py` | Whole-site gate checker | Release / Security | Aggregate release, security, runtime, pytest, and diff checks. | `runtime/reports/security/whole_site_production_gate_*` | Whole-site release criteria are not met. |
| `scripts/security/gate/full_generator_live_validate.py` | Generator live validation | Release / QA | Validate live generator behavior used by gate workflows. | Caller output or production-gate artifact | Generator validation failed or returned incomplete evidence. |
| `scripts/security/gate/header_security_check.py` | Header security | Security | Check HTTP security headers. | Caller output | Security header posture regressed. |
| `scripts/security/gate/scan_plaintext_secrets.py` | Secret scan | Security | Scan tracked text for plaintext secret patterns. | Caller output | A likely plaintext secret is present and must be removed or allowlisted intentionally. |
| `scripts/security/dependency/dep_audit.sh` | Dependency audit | Security | Audit Python dependencies for known issues. | Caller output | Dependency audit found an unacceptable issue. |
| `scripts/security/server_mode/server_mode_v2_clean_smoke.py` | Server-mode smoke | Server Mode / Security | Validate clean mode behavior. | Caller output or production-gate artifact | Server-mode baseline failed. |
| `scripts/security/server_mode/server_mode_v2_adversarial.py` | Server-mode adversarial | Server Mode / Security | Exercise adversarial boundaries. | Caller output or production-gate artifact | A mode boundary or tamper check failed. |
| `scripts/security/server_mode/server_mode_v2_redteam_l2.py` | Server-mode red team | Server Mode / Security | Exercise higher-risk replay/tamper paths. | Caller output or production-gate artifact | High-risk security invariant failed. |
| `scripts/security/server_mode/server_mode_v2_full_smoke.py` | Server-mode broad smoke | Server Mode / QA | Exercise broad server-mode behavior. | Caller output | Selected broad mode smoke failed; not a full production validation alone. |
| `scripts/security/server_mode/server_mode_v2_live_http_smoke.py` | Live HTTP smoke | Server Mode / QA | Exercise live HTTP mode behavior. | Caller output | Live HTTP mode behavior failed. |
| `scripts/security/server_mode/server_mode_v2_phase_5b_acceptance.sh` | Server-mode acceptance | Server Mode / QA | Run phase 5b acceptance checks for Server Mode v2. | Caller output | Acceptance criteria for the phase are not met. |
| `scripts/security/server_mode/server_mode_v2_token_smoke.py` | Token smoke | Server Mode / Auth | Validate tester-token behavior. | Caller output | Token issuance or enforcement regressed. |
| `scripts/testing/pytest_in_tmp.sh` | Pytest wrapper | QA | Run pytest against a `/tmp` copy to avoid repo pollution. | Pytest output; optional caller artifact | Selected pytest suite failed. |

## Non-Gate Maintained Tooling

| Path | Type | Owner | Purpose | Artifact | Failure meaning |
|---|---|---|---|---|---|
| `scripts/admin/root_recovery.py` | Offline recovery | Admin / Security | Recover root credentials outside the web app. | Audit/runtime side effects in target runtime | Recovery could not complete or audit state is invalid. |
| `scripts/comfyui/feature_probe.py` | ComfyUI probe | ComfyUI | Probe local ComfyUI capability metadata. | Console output | Local ComfyUI capability detection failed. |
| `scripts/comfyui/local_connection_smoke.py` | ComfyUI smoke | ComfyUI | Check local ComfyUI connectivity. | Console output | Local ComfyUI is unreachable or incompatible. |
| `scripts/comfyui/materialize_system_workflows.py` | ComfyUI operator | ComfyUI | Materialize system workflow presets. | Runtime/database changes in selected environment | Workflow preset materialization failed. |
| `scripts/games/board_ai_benchmark.py` | Board-game benchmark | Games / ML | Quantify Reversi, Go, and Gomoku local AI strength with round-robin Elo and deterministic skill probes. | `runtime/reports/games/board_ai_benchmark_*` | A board-game AI candidate regressed, produced illegal moves, or lacks measurable strength evidence. |
| `scripts/games/setup_katago.py` | Board-game setup | Games / ML | Download KataGo, a Go neural-network model, and generate the analysis config used by Go `katago` difficulty. | `runtime/katago/` | KataGo neural-network Go difficulty cannot be installed or configured. |
| `scripts/games/chess_exp1_dataset_train.py` | Chess training | Games / ML | Train exp1 from replay-derived FEN/move JSONL datasets. | Target chess experiment DB path | Dataset parsing or exp1 training failed. |
| `scripts/games/chess_exp2_dataset_train.py` | Chess training | Games / ML | Train exp2 neural model from replay-derived datasets. | Target exp2 model path | Dataset parsing or exp2 training failed. |
| `scripts/games/chess_exp3_dataset_train.py` | Chess training | Games / ML | Train exp3 deep-learning model from external or teacher-distilled datasets. | Target exp3 model/replay paths | Dataset parsing, teacher distillation, or exp3 training failed. |
| `scripts/games/chess_exp4_dataset_train.py` | Chess training | Games / ML | Train exp4 policy/value model from replay-derived datasets. | Target exp4 model path | Dataset parsing or exp4 training failed. |
| `scripts/games/chess_exp5_dataset_train.py` | Chess training | Games / ML | Train exp5 NNUE-like evaluator from replay-derived FEN/move datasets. | Target exp5 model/replay paths | Dataset parsing or exp5 NNUE-like training failed. |
| `scripts/games/chess_exp5_teacher_distill.py` | Chess training | Games / ML | Distill teacher-selected moves into exp5-compatible FEN/move JSONL samples. | Selected exp5 JSONL output path | Input FEN parsing, teacher move generation, or output writing failed. |
| `scripts/games/chess_exp5_retrain_pipeline.py` | Chess pipeline | Games / ML | Run the exp5-only minimal replay retrain scaffold without exp3/exp4 semantic gates. | `runtime/reports/games/chess_exp5_retrain_pipeline_*` plus exp5 candidate paths | Exp5 sample parsing, candidate generation, or report writing failed. |
| `scripts/games/chess_exp5_strength_gate.py` | Chess validation | Games / ML | Run the exp5-specific deterministic NNUE/PVS strength gate with optional benchmark safety floors. | `runtime/reports/games/chess_exp5_strength_gate_*` | Candidate schema mismatch, deterministic case failures, or benchmark safety floor failures. |
| `scripts/games/chess_exp4_guarded_overlay_targeted_replay.py` | Chess validation | Games / ML | Replay targeted exp4 guarded-overlay cases for focused regression evidence. | Selected output report or console JSON | Guarded-overlay targeted replay failed or exposed an unsafe move. |
| `scripts/games/chess_exp4_guarded_overlay_unsafe_override_audit.py` | Chess audit | Games / ML | Audit exp4 guarded-overlay unsafe overrides from saved validation artifacts. | Selected audit output directory | Unsafe override semantics are unclear or regression evidence is inconsistent. |
| `scripts/games/chess_exp4_vs_exp5_sparring.py` | Chess sparring | Games / ML | Run exp4 versus exp5 sparring comparisons for candidate quality checks. | Selected sparring output report | Candidate comparison failed or produced invalid chess game evidence. |
| `scripts/games/chess_exp5_adapter_mode_eval.py` | Chess validation | Games / ML | Evaluate exp5 adapter-mode behavior against focused tactical and memory cases. | Selected adapter-mode output directory | Adapter mode regressed, produced illegal moves, or failed scoring floors. |
| `scripts/games/chess_exp5_advanced_score.py` | Chess scoring | Games / ML | Probe advanced exp5 scoring terms and emit focused score diagnostics. | Selected score report or JSONL output | Score terms are inconsistent or do not improve target cases. |
| `scripts/games/chess_exp5_clean_opening_expansion.py` | Chess dataset prep | Games / ML | Build clean held-out opening rows and overlap audits for exp5. | Selected opening expansion output directory | Opening rows are invalid, overlapping, or below the clean-row floor. |
| `scripts/games/chess_exp5_fix_regression.py` | Chess regression | Games / ML | Run focused exp5 regression repair probes against known failing cases. | Selected regression output report | A known exp5 regression remains unfixed or cannot be reproduced. |
| `scripts/games/chess_exp5_focused_benchmark.py` | Chess benchmark | Games / ML | Run focused exp5 benchmark slices for tactical and rule-sensitive behavior. | Selected benchmark output report | Focused benchmark floors failed or illegal move evidence was produced. |
| `scripts/games/chess_exp5_gauntlet.py` | Chess gauntlet | Games / ML | Run deterministic exp5 gauntlet suites across tactical and rule cases. | Selected gauntlet JSONL/report output | Candidate failed a gauntlet case or emitted invalid move evidence. |
| `scripts/games/chess_exp5_holdout_probe.py` | Chess validation | Games / ML | Probe exp5 holdout cases and summarize model behavior before promotion. | Selected holdout output report | Holdout probe failed, regressed, or produced invalid evidence. |
| `scripts/games/chess_exp5_normal_retrain_smoke.py` | Chess smoke | Games / ML | Smoke-test normal exp5 retraining flow without broad promotion. | Selected smoke output directory | Retraining setup, candidate creation, or smoke validation failed. |
| `scripts/games/chess_exp5_opening_candidate_search.py` | Chess search | Games / ML | Search candidate opening positions for exp5 opening-book validation. | Selected candidate-search output directory | Opening candidate generation failed or yielded invalid positions. |
| `scripts/games/chess_exp5_opening_label_audit.py` | Chess audit | Games / ML | Audit opening labels and expected move alternatives for exp5 datasets. | Selected opening-label audit output | Opening labels are inconsistent, illegal, or insufficiently justified. |
| `scripts/games/chess_exp5_opening_overlay_candidate.py` | Chess candidate | Games / ML | Build an exp5 opening overlay candidate for staged evaluation. | Selected overlay candidate artifact | Candidate generation failed or produced invalid overlay metadata. |
| `scripts/games/chess_exp5_opening_overlay_staging_validation.py` | Chess validation | Games / ML | Validate staged opening-overlay candidates before runtime promotion. | Selected staging validation report | Staged candidate failed validation or promotion safety checks. |
| `scripts/games/chess_exp5_production_readiness.py` | Chess validation | Games / ML | Run exp5 production-readiness checks across benchmark and risk rows. | Selected readiness report directory | Production-readiness thresholds failed or suspicious rows need review. |
| `scripts/games/chess_exp5_promote_candidate.py` | Chess operator | Games / ML | Promote a validated exp5 candidate into the selected model location. | Target model artifact and promotion report | Promotion preconditions failed or target artifact could not be written safely. |
| `scripts/games/chess_exp5_quiet_regression_audit.py` | Chess audit | Games / ML | Audit quiet-position regressions for exp5 move quality and safety. | Selected quiet-regression audit output | Quiet move behavior regressed or audit rows are invalid. |
| `scripts/games/chess_exp5_repeatability_gate.py` | Chess validation | Games / ML | Check exp5 repeatability across deterministic seeds and candidate runs. | Selected repeatability report | Candidate is not repeatable or emits inconsistent decisions. |
| `scripts/games/chess_exp5_replay_audit.py` | Chess audit | Games / ML | Audit exp5 replay rows and conversion behavior before training. | Selected replay-audit report | Replay evidence is invalid, duplicated, or unsafe for training. |
| `scripts/games/chess_exp5_score_probe.py` | Chess scoring | Games / ML | Probe exp5 scoring on selected FEN/move cases for diagnosis. | Console JSON or selected score output | Score diagnostics failed or contradicted expected move behavior. |
| `scripts/games/chess_exp5_self_play_anchor.py` | Chess self-play | Games / ML | Generate exp5 self-play anchor games for training and regression review. | Selected self-play output directory | Self-play generation failed or produced invalid replay evidence. |
| `scripts/games/chess_exp5_special_rule_gate.py` | Chess validation | Games / ML | Validate exp5 behavior on castling, promotion, en-passant, and rule-sensitive cases. | Selected special-rule report | Special-rule move handling regressed or produced illegal moves. |
| `scripts/games/chess_exp5_suspicious_audit.py` | Chess audit | Games / ML | Classify suspicious exp5 benchmark rows by model, fixture, or label risk. | Selected suspicious-audit output directory | Suspicious rows remain unexplained or indicate a true model risk. |
| `scripts/games/chess_exp5_tactical_suite.py` | Chess validation | Games / ML | Run tactical exp5 validation suites for checks, captures, and threats. | Selected tactical-suite report | Tactical validation failed or candidate missed required motifs. |
| `scripts/games/chess_imported_replay_teacher_audit.py` | Chess audit | Games / ML | Audit imported replay rows against teacher-selected expectations. | Selected teacher-audit output | Imported replay quality is unsafe for training or review. |
| `scripts/games/chess_pgn_to_replay.py` | Chess dataset prep | Games / ML | Convert PGN games into replay rows for chess training pipelines. | Selected replay JSONL output | PGN parsing or replay conversion failed. |
| `scripts/games/chess_pipeline_dryrun.py` | Chess pipeline | Games / QA | Dry-run the chess data and promotion pipeline without mutating runtime targets. | Selected dry-run report | Pipeline wiring is incomplete or unsafe to execute live. |
| `scripts/games/chess_pipeline_report.py` | Chess reporting | Games / QA | Summarize chess pipeline runs and candidate artifacts for operator review. | Selected markdown or JSON report | Pipeline evidence is missing or inconsistent. |
| `scripts/games/chess_pvp_history_to_replay.py` | Chess dataset prep | Games / ML | Convert PvP history into replay rows for training and auditing. | Selected replay JSONL output | PvP conversion failed or emitted invalid replay rows. |
| `scripts/games/chess_replay_operator.py` | Chess operator | Games / ML | Operate replay ingestion, validation, and export tasks for chess pipelines. | Selected replay output/report | Replay operation failed or violated dataset constraints. |
| `scripts/games/chess_sparring_to_replay.py` | Chess dataset prep | Games / ML | Convert sparring games into replay rows for exp5 training and review. | Selected replay JSONL output | Sparring conversion failed or produced invalid replay rows. |
| `scripts/games/game_ai_codex_play_eval.py` | Game AI evaluation | Games / QA | Run Codex-assisted play/evaluation probes across game AI modules. | Selected game AI evaluation report | Game AI behavior regressed or probe evidence is incomplete. |
| `scripts/games/game_ai_live_smoke.py` | Game AI smoke | Games / QA | Smoke-test live game AI endpoints and frontend integration. | Console output or selected smoke report | Live game AI route or frontend integration failed. |
| `scripts/games/game_ai_strength_eval.py` | Game AI evaluation | Games / QA | Quantify board-game AI strength and qualitative skill factors. | Selected strength-evaluation report | AI strength evidence is missing, illegal, or below expected floors. |
| `scripts/games/chess_live_learning_validation.py` | Chess validation | Games / QA | Validate live replay classification, quarantine, retraining, and promotion behavior. | `/tmp/chess_live_learning_validation_*` or selected output root | Chess live-learning regression or promotion gate behavior failed. |
| `scripts/games/chess_model_import.py` | Chess operator | Games / ML | Validate and install external chess model weights. | Target runtime model path or validation JSON | Model shape, metadata, or install validation failed. |
| `scripts/games/chess_replay_prepare.py` | Chess dataset prep | Games / ML | Build filtered train/eval JSONL datasets from replay ledgers. | Selected output directory under reports/runtime | Replay filtering or dataset generation failed. |
| `scripts/games/chess_seed_train.py` | Chess training | Games / ML | Train directly usable seed artifacts for chess experiment engines. | `runtime/games/models/` and `runtime/reports/games/` or explicit paths | Seed training, smoke, or benchmark failed. |
| `scripts/games/chess_self_play_train.py` | Chess training | Games / ML | Train chess practice engines through automated self-play. | `runtime/games/models/` and `runtime/reports/games/` or explicit paths | Self-play training, smoke, or benchmark failed. |
| `scripts/games/chess_train_pipeline.py` | Chess pipeline | Games / ML | Run replay preparation, training, benchmark, staging, and promotion pipeline. | `runtime/reports/games/chess_train_pipeline_*` plus candidate model paths | Pipeline stage, benchmark, staging, or promotion failed. |
| `scripts/testing/playwright_comfyui_workflow_builder_check.py` | Playwright QA | QA / ComfyUI | Validate the ComfyUI visual workflow builder with real Chromium interactions. | Console output and optional Playwright traces | Workflow builder UI or mobile layout regressed. |
| `scripts/testing/playwright_deep_site_check.py` | Playwright QA | QA | Run deep authenticated site flow checks against an isolated runtime. | Runtime QA report under selected temp root | A broad authenticated user flow regressed. |
| `scripts/testing/playwright_full_site_check.py` | Playwright QA | QA | Run full-site Playwright coverage for key modules and layouts. | Runtime QA report under selected temp root | A full-site frontend flow or layout check failed. |
| `scripts/testing/playwright_mobile_viewports.py` | Playwright QA | QA / Frontend | Validate selected pages across mobile viewport sizes. | Console output or selected screenshot/report directory | Mobile layout regressed or overflows. |
| `scripts/testing/playwright_platform_health_check.py` | Playwright QA | QA / Platform | Validate platform center jobs, notifications, shares, trading overview, and mobile health. | `runtime/reports/qa/playwright_platform_health_check_*` | Platform center behavior or layout regressed. |
| `scripts/testing/playwright_visual_health_check.py` | Playwright QA | QA / Frontend | Run visual health checks for frontend pages and components. | Console output or selected screenshot/report directory | Frontend rendering or visual stability regressed. |
| `scripts/testing/register_qa_artifacts.py` | QA utility | QA | Register QA artifacts for later report indexing and review. | Selected artifact index output | QA artifact registration failed or metadata is incomplete. |
| `scripts/testing/run_playwright_acceptance.sh` | Playwright wrapper | QA | Run the CI Playwright acceptance sequence. | Console output and isolated runtime reports | Acceptance flow failed in a way that should block CI. |
| `scripts/prepush/pre_push_checks.py` | Pre-push runner | Release / QA | Run local pre-push checks. | Console output | The branch is not ready to push. |
| `scripts/trading/bridges/btc_signal_bridge.py` | Trading bridge | Trading / Integration | Bridge optional BTC_trade runtime signals into hackme_web simulated spot orders. | Console JSON/status and trading DB side effects | BTC_trade status read or bridge order placement failed. |
| `scripts/trading/validation/trading_exchange_validation.py` | Trading validation | Trading | Validate exchange integration assumptions. | Console output | Exchange integration is unavailable or inconsistent. |
| `scripts/trading/validation/trading_workflow_template_validation.py` | Trading validation | Trading | Validate trading workflow templates. | Console output | Trading workflow template behavior regressed. |
| `scripts/trading/competition/trading_backtest_benchmark.py` | Trading benchmark | Trading | Benchmark trading backtest behavior. | Benchmark output | Performance or correctness expectations failed. |
| `scripts/trading/competition/workflow_template_backtest_benchmark.py` | Trading benchmark | Trading | Benchmark workflow-template backtests. | Benchmark output | Workflow backtest behavior or performance regressed. |
| `scripts/trading/probes/backtest_20000_probe.py` | Trading probe | Trading / QA | Probe 20,000-candle segmented backtests and route payload behavior. | Console JSON or `--json-out` path | Backtest segmentation, route payload, or edge-case handling failed. |

## Wrapper Registration

`scripts/on_live_reports/` contains stable operator-facing wrappers and
symlinks. The implementation path remains the source of behavior; the wrapper
path remains the stable production-gate or operator path. Adding a wrapper
requires:

1. a row in this file;
2. a clear implementation target;
3. a compatibility reason;
4. a removal policy if it is temporary.
