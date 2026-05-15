# Exp5 Held-Out Stockfish Validation 50

日期：2026-05-14

## 目的

依照「固定題保留為衡量基準、另做驗證題避免過擬合」的方向，新增一組不參與 exp5 gauntlet scoring / model priors 的 50 題 held-out validation probes。每題取一個 line-ending/key position，由 exp5 下單手，再交給本地外部 Stockfish teacher 以 MultiPV 審核。

這裡的 `blockfish teacher` 以目前已接入的本地 Stockfish UCI teacher 執行；Stockfish binary 不進 repo，不作為線上依賴。

## 腳本與調用地圖

新增腳本：

```text
scripts/games/chess_exp5_validation_probe.py
  -> 內建 50 題 held-out validation positions（敏感題庫，不在報告公開逐題內容）
  -> services/games/chess_nnue.py::choose_experiment_nnue_move(...)
  -> services/games/chess_stockfish_teacher.py::UciStockfish MultiPV
  -> docs/games/evidence/exp5/*heldout_validation_50_stockfish.{json,jsonl}
```

已同步更新：

- `scripts/INDEX.md`
- `scripts/CALL_MAP.md`

## 執行紀錄

Smoke：

```bash
python3 -m py_compile scripts/games/chess_exp5_validation_probe.py
python3 scripts/games/chess_exp5_validation_probe.py \
  --questions 50 \
  --profiles fixed_depth_balanced \
  --depth 1 \
  --multipv 1 \
  --output-json /tmp/chess_exp5_validation_probe_smoke.json \
  --output-jsonl /tmp/chess_exp5_validation_probe_smoke.jsonl
```

正式驗證：

```bash
python3 scripts/games/chess_exp5_validation_probe.py \
  --questions 50 \
  --profiles fixed_depth_balanced,fixed_depth_piece_activity_midgame \
  --depth 8 \
  --multipv 5 \
  --output-json docs/games/evidence/exp5/v20_heldout_validation_50_stockfish.json \
  --output-jsonl docs/games/evidence/exp5/v20_heldout_validation_50_stockfish.jsonl
```

輸出：

- `docs/games/evidence/exp5/v20_heldout_validation_50_stockfish.json`
- `docs/games/evidence/exp5/v20_heldout_validation_50_stockfish.jsonl`

JSONL 行數：100（50 題 x 2 profiles）。

保密原則：

- 報告只公開彙總統計與分類結論。
- 不公開 held-out 題號、FEN、candidate move、teacher move、逐題 CP loss 或任何可還原題目的內容。
- 原始 JSONL 只作本機追蹤與重現，不應作為公開報告內容。

Teacher：

- Stockfish reference：`dd321af5dfc0789de07c4e5c64915073995eb818`
- limit：depth 8
- MultiPV：5
- clean：rank <= 3 或 cp loss <= 60
- review：cp loss <= 160

## 結果摘要

| Profile | Clean | Review | Rejected | Top1 | Top3 | Top5 | Avg CP Loss | Max CP Loss |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `fixed_depth_balanced` | 38/50 | 10/50 | 2/50 | 10/50 | 20/50 | 30/50 | 47.70 | 248 |
| `fixed_depth_piece_activity_midgame` | 39/50 | 9/50 | 2/50 | 13/50 | 22/50 | 33/50 | 41.26 | 248 |

結論：v20 candidate 在 held-out validation 上小幅優於 baseline，但不是壓倒性提升。主要改善在 gambit / closed-center / flank 類別，quiet positional 仍然不穩。

## 對 Baseline 的變化

基於不洩題原則，這裡只保留分類層級摘要：

- 改善較明顯：部分 gambit / closed-center / early-development 類題目，Stockfish top-K 對齊率提升。
- 仍需觀察：human-probe / quiet-positional 類題目，候選手偶爾仍偏短視。
- 高風險類別：gambit 中心反擊時機、側翼開局的發展優先級、非唯一好手局面的排序穩定性。

## 評價

這組驗證題比原本固定 gauntlet 更能暴露泛化問題，尤其是 gambit/human-probe/quiet-positional 的非唯一好手局面。v20 的 piece activity midgame gate 確實提高了 Stockfish topK 對齊率與平均 cp loss，但仍無法解決兩類核心缺陷：

1. gambit 中的中心反擊時機仍不穩。
2. flank / quiet position 的發展優先級仍不穩。

下一步不應把這 50 題寫成硬編碼 priors；這份驗證集應保留為 held-out。若要繼續提升，應從 eval/search 結構處理「中心反擊」「fianchetto 發展」「gambit 補償」等可泛化特徵。
