# Governance QA Gate v1

> **Status：Design draft (Claude, 2026-05-06). Approval pending. Implementation blocked until PointsChain v2 Phase 1 / 2 / 4 / 6 complete + Governance Phase G-4 authorization.**
>
> 屬 [GOVERNANCE_FRAMEWORK.md](GOVERNANCE_FRAMEWORK.md) §2 維度 12。

---

## 0. 設計參照

| 系統 | 借鑑 |
|---|---|
| **Uniswap Seatbelt** | proposal payload simulation + state diff 對比 |
| **OpenZeppelin Governor 測試慣例** | quorum / threshold / timelock / payload integrity 為各自獨立測試 |
| **Cosmos governance test suite** | deposit refund / forfeit 路徑單元測試 |
| **PointsChain Phase 0 cleanup gate** | 測試覆蓋率作為 release gate |

---

## 1. 為什麼需要獨立的 Governance QA Gate

PointsChain 既有 [POINTSCHAIN_QA.md](POINTSCHAIN_QA.md) 涵蓋 ledger / wallet / chain block，但**沒有覆蓋 governance 的攻擊面**：

```
- 沒投票權的人能不能投？
- 改了 payload 後 timelock 還能 execute 嗎？
- 提案者 / 執行者 / 投票者三角能不能互審自批？
- treasury 超 budget 能不能 spend？
- mint 超 hard cap 能不能執行？
- emergency pause 後 transfer / trading / mint 是否真的全停？
- root / admin 能不能跳過 proposal 直接改 governance parameter？
- proposal spam / duplicate 是否被拒？
```

每個都要寫成獨立 pytest，一次跑全過才放 governance 上線。

---

## 2. 12 條必過測試

### G-QA-1：未達提案門檻不可提案

```python
def test_proposal_below_threshold_rejected():
    user = make_user(trust_score=40)  # < 50 minimum eligibility
    res = submit_proposal(proposer=user, tier='L1')
    assert res.status_code == 403
    assert 'eligibility' in res.json()['msg']
    assert governance_proposals_count() == 0
```

也要測 deposit 不足：

```python
def test_proposal_below_deposit_rejected():
    user = make_eligible_user(balance=10)  # below L1 deposit (e.g. 500)
    res = submit_proposal(proposer=user, tier='L1', deposit=10)
    assert res.status_code == 400
    assert 'deposit' in res.json()['msg']
```

### G-QA-2：Quorum 不足不通過

```python
def test_proposal_quorum_not_met_expired():
    p = create_active_proposal(tier='L3', vote_period_seconds=10)
    # vote 但只達 10% 的 quorum (L3 要 30%)
    cast_vote(p, weight=0.1 * eligible_total_weight, vote='yes')
    advance_time(seconds=11)
    finalize_voting(p)
    p.refresh()
    assert p.status == 'expired'
    assert get_ledger_event_count(proposal_id=p.id, event_type='proposal_expired') == 1
```

### G-QA-3：Veto threshold 達標必須阻擋

```python
def test_proposal_vetoed_when_veto_threshold_met():
    p = create_active_proposal(tier='L3')
    cast_vote(p, weight=0.7 * eligible_total_weight, vote='yes')
    cast_vote(p, weight=0.4 * eligible_total_weight, vote='veto')  # > 33% veto
    finalize_voting(p)
    assert p.refresh().status == 'vetoed'
    # 即使 yes > pass threshold 仍被擋
```

### G-QA-4：Timelock 未到不可執行

```python
def test_execute_before_timelock_rejected():
    p = create_passed_proposal(tier='L3', timelock_seconds=86400 * 7)
    queue_proposal(p)
    advance_time(seconds=86400 * 6)  # 7 天差 1 天
    res = execute_proposal(p, executor=root_actor)
    assert res.status_code == 400
    assert 'timelock' in res.json()['msg']
```

### G-QA-5：Payload hash 被改不可執行

對標 Uniswap Seatbelt — proposal 鎖 payload 後 hash 不可變。

```python
def test_execute_with_tampered_payload_rejected():
    p = create_passed_proposal(payload={'amount': 1000})
    queue_proposal(p)
    advance_to_executable(p)
    # 攻擊嘗試 — 把 payload 改大
    sql_direct_update(table='governance_proposals', id=p.id, payload_json='{"amount": 10000000}')
    res = execute_proposal(p, executor=root_actor)
    assert res.status_code == 400
    assert 'payload_hash' in res.json()['msg']
    # 或：execute 流程寫死，每次重新計算 hash 比對
```

### G-QA-6：Execution state diff 必須符合 simulation

```python
def test_execute_state_diff_matches_simulation():
    p = create_passed_proposal(payload={
        'action': 'mint', 'destination': 'PNT1REWARD', 'amount': 1000
    })
    advance_to_executable(p)
    expected_diff = simulate(p)
    assert p.expected_state_diff_hash == hash(expected_diff)

    execute_proposal(p, executor=root_actor)
    actual = collect_state_diff(p.executed_at, p.executed_at + 1s)

    p.refresh()
    assert p.actual_state_diff_hash == p.expected_state_diff_hash
    assert PNT1REWARD.balance_after - PNT1REWARD.balance_before == 1000
```

不一致：

```python
def test_execute_state_diff_mismatch_triggers_rollback():
    p = create_passed_proposal(payload={
        'action': 'mint', 'destination': 'PNT1REWARD', 'amount': 1000
    })
    monkey_patch_mint_to_inflate(2000)  # bug：mint 多了
    advance_to_executable(p)
    execute_proposal(p, executor=root_actor)

    # 系統應自動偵測 + 啟動 rollback proposal
    assert p.refresh().status == 'rolled_back'
    rollback = find_emergency_event(action='emergency_burn', source='PNT1REWARD', amount=2000)
    assert rollback is not None
```

### G-QA-7：Multisig signer 不可自審自批

```python
def test_proposer_cannot_self_approve_multisig():
    proposer = council_member(role='security_council')
    p = create_proposal_requiring_multisig(proposer=proposer, tier='L3')
    advance_to_voting(p)
    res = cast_multisig_signature(p, signer=proposer)
    assert res.status_code == 403
    assert 'self_approve' in res.json()['msg']
```

也測 propose + execute 同人：

```python
def test_proposer_cannot_be_executor():
    p = create_passed_proposal(proposer=alice, tier='L3')
    advance_to_executable(p)
    res = execute_proposal(p, executor=alice)
    assert res.status_code == 403
    assert 'self_execute' in res.json()['msg']
```

### G-QA-8：Treasury payout 不可超 budget

```python
def test_treasury_spend_over_budget_rejected():
    budget = create_active_budget(name='security_council', cap=1000, spent=900)
    p = create_passed_proposal(payload={
        'budget_id': budget.id, 'amount': 200, 'to_address': '...'
    })
    advance_to_executable(p)
    res = execute_proposal(p, executor=committee_signer)
    assert res.status_code == 400
    assert 'over_budget' in res.json()['msg']
    assert budget.refresh().spent_amount == 900  # 沒被改
```

### G-QA-9：Mint 不可超 hard cap / emission cap

```python
def test_mint_over_hard_cap_rejected():
    set_param('mint.core_points.hard_cap', 1_000_000)
    set_total_supply(990_000)
    p = create_passed_proposal(payload={
        'action': 'mint', 'destination': 'PNT1TREASURY', 'amount': 50_000
    })  # 990k + 50k = 1.04M > 1M
    advance_to_executable(p)
    res = execute_proposal(p, executor=root_actor)
    assert res.status_code == 400
    assert 'hard_cap' in res.json()['msg']

def test_mint_over_rolling_30day_cap_rejected():
    # 過去 30 天已 mint 2.8% of circulating, 此次再 mint 0.5%
    # 30-day cap = 3% → 應拒
    record_recent_mints(percent=2.8)
    p = create_passed_proposal(payload={
        'action': 'mint', 'destination': 'PNT1REWARD',
        'amount': int(0.005 * current_circulating())
    })
    res = execute_proposal(p, executor=root_actor)
    assert res.status_code == 400
    assert '30day_cap' in res.json()['msg']
```

### G-QA-10：Emergency pause 後 transfer / trading / mint / reward payout 全停

```python
def test_emergency_pause_stops_all_actions():
    trigger_emergency_event(action='emergency_pause', scope='all')
    # 各種寫入操作全部被擋
    for endpoint in [
        '/api/points/transfer/preview',
        '/api/trading/orders',
        '/api/governance/proposals/<some>/execute',  # 即使 timelock 到也擋
        '/api/admin/points/grant',                    # reward payout
    ]:
        res = api_post(endpoint, body={...})
        assert res.status_code == 503
        assert 'emergency' in res.json()['msg']
    # 讀取仍可
    res = api_get('/api/points/wallet')
    assert res.status_code == 200
```

### G-QA-11：Admin / root 不可跳過 proposal 直接改 governance parameter

```python
def test_root_cannot_directly_update_governance_param():
    # 嘗試 SQL 直寫 governance_parameters
    with pytest.raises(sqlite3.IntegrityError):
        sql_direct_update(
            table='governance_parameters',
            param_key='mint.core_points.hard_cap',
            current_value='99999999999'
        )
    # 嘗試 API 直接 PUT
    res = api_put(
        '/api/admin/system-settings',
        body={'mint.core_points.hard_cap': 99999999999},
        actor=root_actor,
    )
    assert res.status_code == 403
    assert 'governance_parameter' in res.json()['msg']
    # 必須走 proposal
    p = create_passed_proposal(payload={
        'param_key': 'mint.core_points.hard_cap', 'to_value': '99999999999'
    })
    advance_to_executable(p)
    execute_proposal(p, executor=root_actor)
    assert get_param('mint.core_points.hard_cap') == 99999999999
```

### G-QA-12：Proposal spam / duplicate 要被拒

```python
def test_duplicate_payload_within_30day_window_rejected():
    payload = {'action': 'mint', 'destination': 'PNT1REWARD', 'amount': 1000}
    p1 = submit_proposal(payload=payload, tier='L3')
    advance_time(days=10)
    res = submit_proposal(payload=payload, tier='L3')  # same payload hash
    assert res.status_code == 400
    assert 'duplicate' in res.json()['msg']

def test_proposer_spam_score_triggers_cooldown():
    user = make_eligible_user()
    # 連續 3 次 spam（rejected as spam）
    for _ in range(3):
        p = submit_proposal(proposer=user, payload=spam_payload(), tier='L1')
        flag_as_spam(p)
    res = submit_proposal(proposer=user, tier='L1')
    assert res.status_code == 403
    assert 'cooldown' in res.json()['msg']
    advance_time(days=89)
    res = submit_proposal(proposer=user, tier='L1')
    assert res.status_code == 403  # 還沒過 cooldown
    advance_time(days=2)
    res = submit_proposal(proposer=user, tier='L1')
    assert res.status_code == 200  # 過了
```

---

## 3. 補充測試（建議 Phase 2 覆蓋）

| 測試 | 描述 |
|---|---|
| G-QA-13 | objection signal 達 50% 自動 vetoed |
| G-QA-14 | sybil cluster 投票權自動歸零 + 重算 quorum |
| G-QA-15 | Bicameral：兩院都過才通過 |
| G-QA-16 | delegation cycle 自動偵測 + 拒絕 |
| G-QA-17 | governance lock 提前釋放罰金正確進 dispute pool |
| G-QA-18 | snapshot：vote_start_at 之後 trust_score 變動不影響該 proposal |
| G-QA-19 | postmortem 未交 → committee 自動 30 天 cooldown |
| G-QA-20 | ratification rejected → 影響的 mint / burn 可被 reverse |

---

## 4. Release Gate

Governance Phase G-0 .. G-4 任一階段上線前，這 12 條 **MUST 全部 PASS**：

```bash
pytest tests/test_governance_qa_gate.py -v
# 12 / 12 passed
```

加上 PointsChain v2 既有的 QA gate（[POINTSCHAIN_QA.md](POINTSCHAIN_QA.md)），合計 governance 上線前需要：

```
PointsChain Phase 1-6 QA: existing
Governance G-QA-1..12:    new (this file)
GOVERNANCE_QA_GATE 簽核：root + Security Council 2-of-3
```

---

## 5. 失敗時的處置

| Test | Fail 後動作 |
|---|---|
| G-QA-1 / G-QA-12 | 提案 schema / spam guard 邏輯有 bug — 阻擋 governance 上線 |
| G-QA-2 / G-QA-3 | quorum / veto 計算錯 — 阻擋 |
| G-QA-4 / G-QA-5 | timelock / payload integrity 問題 — **絕對阻擋**（這是治理核心） |
| G-QA-6 | simulation framework bug — 阻擋；需先補 |
| G-QA-7 | self-approve 防護失靈 — **絕對阻擋**（防 collusion 核心） |
| G-QA-8 / G-QA-9 | budget / hard cap / emission cap 任一失靈 — **絕對阻擋**（經濟安全） |
| G-QA-10 | emergency pause 沒擋住一些 endpoint — 阻擋；補 endpoint coverage |
| G-QA-11 | governance_parameter 直寫防護失靈 — **絕對阻擋** |

---

## 6. CI 整合

加入 `security/server_mode_v2_phase_5b_acceptance.sh` 的同類 pattern：

```bash
# security/governance_qa_gate.sh (proposed)
pytest -q tests/test_governance_qa_gate.py
pytest -q tests/test_governance_proposal_lifecycle.py
pytest -q tests/test_governance_voting_power.py
pytest -q tests/test_governance_treasury_budget.py
pytest -q tests/test_emergency_governance.py
```

每個 sub-suite 對應一個 governance 文件。

---

## 7. 跨參考

- [GOVERNANCE_FRAMEWORK.md](GOVERNANCE_FRAMEWORK.md)
- [GOVERNANCE_PROPOSAL_LIFECYCLE.md](GOVERNANCE_PROPOSAL_LIFECYCLE.md)
- [GOVERNANCE_VOTING_POWER.md](GOVERNANCE_VOTING_POWER.md)
- [TREASURY_BUDGET_POLICY.md](TREASURY_BUDGET_POLICY.md)
- [POINTS_MONETARY_POLICY.md](POINTS_MONETARY_POLICY.md)
- [EMERGENCY_GOVERNANCE.md](EMERGENCY_GOVERNANCE.md)
- [DISPUTE_AND_APPEALS.md](DISPUTE_AND_APPEALS.md)
- [POINTSCHAIN_QA.md](POINTSCHAIN_QA.md)
- 設計參照：Uniswap Seatbelt simulation / OpenZeppelin Governor 測試慣例 / Cosmos governance test suite
