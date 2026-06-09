# mt5-mcp-server

AIに **MetaTrader 5 の Strategy Tester** を自動操作させる **MCP サーバー**（Python / FastMCP / stdio）。
Claude Code などのMCPクライアントから「このEAをEURUSD H1で2024年バックテストして最適化して」と頼むと、
`.ini`生成 → `terminal64.exe`起動 → 完了待ち → レポート解析 → 構造化結果、を自動で行います。

> **Windows 専用**（MT5 Strategy Tester は Windows のみ）。Python 3.10+。

## ツール

| ツール | 概要 |
|---|---|
| `mt5_info` | 既定MT5・データフォルダ・ビルド・EA数・起動中かを検出（セットアップ確認用） |
| `list_mt5_terminals` | 検出した全MT5インストール（ブローカー別）を一覧 |
| `list_eas` | `MQL5/Experts/` の `.ex5` を一覧（`rel_path` を `ea` に渡す） |
| `run_backtest` | 単一バックテスト → 純益/PF/DD/勝率/取引数等を返す |
| `optimize` | 遺伝的最適化 → ベストN・最適パラメータ（`min_trades` で取引数下限） |
| `run_forward_test` | 固定パラメータでOOS（アウトオブサンプル）テスト |
| `full_pipeline` | IS最適化 → OOS検証 → 過剰最適化チェックを一括 |

## 必要環境

- **Windows 10/11**
- **Python 3.10+**
- **MetaTrader 5 がインストール済み**で、**対象口座にログイン済み**かつテスト銘柄の**履歴がダウンロード済み**であること
  （未ログイン/履歴なしだとレポートは出るが `history_quality=0%`・0トレードの空結果になります）

## インストール

```powershell
# pipx（推奨・隔離インストール）
pipx install git+https://github.com/iwanao513/mt5-mcp-server
# PyPI公開後は:  pipx install mt5-mcp-server

# uvx（ゼロインストール実行）
uvx --from git+https://github.com/iwanao513/mt5-mcp-server mt5-mcp-server
# PyPI公開後は:  uvx mt5-mcp-server

# ソースから（開発）
git clone https://github.com/iwanao513/mt5-mcp-server
cd mt5-mcp-server
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
```

いずれの場合も `mt5-mcp-server` という実行ファイルが PATH（または venv）に入ります。

## MCP クライアントへの登録

stdio サーバーです。どのクライアントも `command`/`args` の形は同じで、設定ファイルが違うだけです。

**Claude Code**
```powershell
claude mcp add mt5 -- mt5-mcp-server
# venv にだけ入れた場合は実行ファイルのフルパスを渡す:
#   claude mcp add mt5 -- "<REPO>\.venv\Scripts\mt5-mcp-server.exe"
```

**Claude Desktop**（`%APPDATA%\Claude\claude_desktop_config.json`）
```json
{ "mcpServers": { "mt5": { "command": "mt5-mcp-server", "args": [] } } }
```

**Cursor**（`.cursor/mcp.json`）/ **Windsurf**（`~/.codeium/windsurf/mcp_config.json`）/ **VS Code**（`.vscode/mcp.json` は `servers` キー）も同じ `command: "mt5-mcp-server"` で登録できます。

確認: `claude mcp list` / `claude mcp get mt5` / クライアント内で `/mcp`。

## 使い方

1. `mt5_info()` で検出を確認（`is_running` が true なら対象MT5を一度閉じる）。
2. `list_eas("moving")` でEAの `rel_path` を得る。
3. `run_backtest(ea="Examples\\Moving Average\\Moving Average.ex5", symbol="EURUSD", from_date="2024.01.01", to_date="2024.06.30", period="H1")`。
4. `optimize(ea=..., symbol="EURUSD", from_date="2024.01.01", to_date="2024.04.30", param_ranges={"MovingPeriod":[8,40,2],"MovingShift":[0,10,2]}, min_trades=40)`。
5. `full_pipeline(...)` で IS最適化→OOS検証→過剰最適化判定までを一括。

> `list_eas` が空なら、MetaEditor を一度開いて `MQL5/Experts/Examples`（や任意のEA）をコンパイルしてください。**コンパイル済み `.ex5` のみテスト可能**です。

## どのMT5を使うか（複数インストール対応）

`list_mt5_terminals()` で候補（ブローカー別・ビルド）を確認し、対象を**パスで指定**できます。

- ツール引数 `terminal_path`（呼び出しごと）: 例 `run_backtest(..., terminal_path="C:\\Program Files\\XMTrading MT5\\terminal64.exe")`
- 既定として固定: ユーザー設定（下記）の `terminal_path`

未指定なら **config → `C:\Program Files\MetaTrader 5`（あれば）→ レジストリ（ブローカー版含む）** の順で自動検出します。

## 設定

設定は次の順で読み、後勝ちでマージされます（**どれも無くても既定値で動作**）:

1. リポジトリ同梱 `config/mt5_config.json`（dev用テンプレ・全null）
2. **ユーザー設定 `%APPDATA%\mt5-mcp-server\mt5_config.json`**（インストール利用はここ）／同 `mt5_config.local.json`
3. 環境変数 `MT5_MCP_CONFIG`（任意のJSONフルパス）

| キー | 既定 | 説明 |
|---|---|---|
| `terminal_path` | 自動検出 | terminal64.exe のフルパス（または親フォルダ） |
| `data_folder` | 自動検出 | origin.txt から逆引き |
| `default_deposit`/`default_currency`/`default_leverage` | 10000/USD/1:100 | |
| `default_model` | 1 | 0=全ティック,1=1分OHLC,2=始値,4=実ティック |
| `backtest_timeout_sec`/`optimization_timeout_sec` | 1200/7200 | |
| `login`/`password`/`server` | （未設定） | ヘッドレス自動ログイン用（下記） |

### ヘッドレス自動ログイン（履歴も自動DL）

未ログインのMT5を使う場合、ユーザー設定に**口座情報**を入れると `.ini` の `[Common]` 経由で起動時に自動ログインし、足りない履歴を自動DLします:

```json
{ "terminal_path": "C:\\Program Files\\XMTrading MT5\\terminal64.exe",
  "login": 12345678, "password": "デモ口座パスワード", "server": "XMTrading-Demo" }
```

> ⚠️ **デモ口座を強く推奨**（ライブのパスワードを平文で置かない）。`mt5_config.local.json` は gitignore 済み。**`terminal_path`/`login`/`password` を tracked な `mt5_config.json` に書かない**こと（コミット事故防止）。

## 過剰最適化を避ける

`full_pipeline` は **IS（最適化）/ OOS（検証）期間を分割**し、OOSでPFが崩れる・不採算・取引過少なら `overfit_warning` を立てます。
`min_trades` で**取引数の下限**を課し、少数のまぐれ当たりに最適化されたパラメータを除外できます。
最適化するパラメータは**少なく**保つのが安全です。

## トラブルシューティング

| 症状 | 原因 / 対処 |
|---|---|
| `terminal64.exe not found` | MT5未検出。`list_mt5_terminals()` で確認、または設定に `terminal_path` を記入 |
| `MetaTrader 5 is already running` | 対象MT5が起動中。閉じるか `close_running=true` |
| `no report produced` / `history_quality=0%` / 0トレード | 未ログイン or 履歴なし。MT5で対象口座にログイン＆履歴DL（または設定に login/password/server） |
| `authorization ... (Old version)` | その端末のビルドが古くサーバに拒否。端末を更新、または最新ビルドの端末を使う |
| `list_eas` が空 | `.ex5` が無い。MetaEditor でEAをコンパイル |

## 安全・免責

- バックテスト/トレードにはリスクがあります。本ツールは検証補助であり、結果や戦略の良否を保証しません。
- `close_running` は対象MT5を**終了させます**（既定 false・明示オプトイン）。
- stdio ローカルサーバーで外部公開はありません。認証情報はローカル設定のみで扱い、決してコミットしないでください。

## ライセンス

MIT License — see [LICENSE](LICENSE).
