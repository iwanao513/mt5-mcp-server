# mt5-mcp-server

AIがMetaTrader 5 の Strategy Tester を自動操作するための **MCPサーバー**（Python）。Claude Code から
「このEAをUSDJPY H1で2024年バックテストして最適化して」と頼むと、`.ini`生成 → `terminal64.exe`起動 →
完了待ち → レポート解析 → 構造化結果を返す、を自動で行う。

- **言語**: Python 3.10+
- **MCP**: 公式 `mcp` SDK（FastMCP, stdio）
- **MT5連携**: `terminal64.exe /config:xxx.ini`（UTF-16）+ レポート解析（HTML/XML）
- **OS**: Windows 専用（Strategy Tester の制約）

## ツール

| ツール | 概要 |
|---|---|
| `mt5_info` | MT5本体・データフォルダ・ビルド・EA数・起動中かを検出 |
| `list_eas` | `MQL5/Experts/` の `.ex5` 一覧（`rel_path` を `ea` に渡す） |
| `run_backtest` | 単一バックテスト → 純益/PF/DD/勝率/取引数等を返す |
| `optimize` | 遺伝的最適化（Optimization=2）→ ベストN・最適パラメータ |
| `run_forward_test` | 固定パラメータでOOS（アウトオブサンプル）テスト |
| `full_pipeline` | IS最適化 → OOS検証 → 過学習チェックを一括 |

## セットアップ

```powershell
cd C:\Users\PCUSER\Projects\mt5-mcp-server
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

### Claude Code に登録

```powershell
claude mcp add mt5 -- C:\Users\PCUSER\Projects\mt5-mcp-server\.venv\Scripts\mt5-mcp-server.exe
```

もしくはプロジェクト同梱の `.mcp.json`（このリポジトリ直下）をそのまま使う（プロジェクトスコープ、初回は承認が必要）。
確認: `claude mcp list` / `claude mcp get mt5` / Claude Code内で `/mcp`。

## 使い方の例（Claude Code から）

1. `mt5_info()` で検出を確認（`is_running` が true なら対象MT5を一度閉じる）。
2. `list_eas("moving")` でEAの `rel_path` を得る。
3. `run_backtest(ea="Examples\\Moving Average\\Moving Average.ex5", symbol="EURUSD", from_date="2024.01.01", to_date="2024.06.30", period="H1")`。
4. `optimize(ea=..., symbol="EURUSD", from_date="2023.01.01", to_date="2024.06.30", param_ranges={"MovingPeriod":[10,40,2],"MovingShift":[0,10,1]})`。
5. `run_forward_test(ea=..., symbol="EURUSD", from_date="2024.07.01", to_date="2024.12.31", inputs=optimize_best_params)`。

## 設定（`config/mt5_config.json`）

| キー | 既定 | 説明 |
|---|---|---|
| `terminal_path` | null | 自動検出（レジストリ/既知パス）。明示する場合は terminal64.exe のフルパス |
| `data_folder` | null | 自動検出（origin.txt 逆引き） |
| `default_deposit` / `default_currency` / `default_leverage` | 10000 / USD / 1:100 | |
| `default_model` | 1 | 0=全ティック,1=1分OHLC,2=始値,4=実ティック |
| `backtest_timeout_sec` / `optimization_timeout_sec` | 1200 / 7200 | |

## 重要な制約・注意

- **単一インスタンス制約**: 対象データフォルダのMT5が起動中だと `/config` 実行が無視される。`run_backtest` は起動中を検出して中止する（`close_running=true` で先に閉じることも可能）。
- **ヒストリー/ログイン**: 初回の銘柄/期間はヒストリーDLが必要。MT5でアカウントにログイン済み＆対象銘柄の履歴がある状態が前提。無いとレポートが生成されず失敗する。
- **レポートのラベルはUI言語依存**（日本語環境なら日本語）。パーサはEN+JAエイリアスで対応し、`raw`に全ラベルも返す。
- 単一テストは拡張子に関わらず常にHTML。最適化のみXML（SpreadsheetML）。
- `.ini`はUTF-16で書き出す。`Visual=0`/`ShutdownTerminal=1` でヘッドレス＆完了検知。

## 構成

```
src/mt5_mcp_server/
  paths.py          MT5本体/データフォルダ/EA検出（レジストリ・origin.txt）
  ini_builder.py    /config .ini 生成（[Tester]/[TesterInputs], UTF-16）
  report_parser.py  HTML(単一)・XML(最適化)解析、EN+JAラベル
  runner.py         terminal64起動・完了検知（プロセス終了+レポートmtime）
  server.py         FastMCP サーバ（ツール定義）
config/mt5_config.json
.mcp.json           Claude Code 登録用
```
