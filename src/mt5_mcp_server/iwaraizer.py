"""Convert MT5 backtest trades into 岩ライザーFX (Iwaraizar FX) format and feed its keepdata.

The app reads %APPDATA%\\iwaraizar_fx_public\\keepdata\\Contents.json. Structure:
    [ { "Contents": [ <meta>, <trade>, <trade>, ... ] }, ... ]   # one element per dataset
meta  = {mode, title, FirstEquity(str), Parameter(str), ModelingQuality(str), Spred(str)}
trade = {EntryTime,FinishTime "YYYY/MM/DD HH:MM", EntryPrice/FinishPrice(str), type(buy/sell),
         Lot, Profit(net), Commission, Swap, Balance, title, No(str), symbol}
The app file-watches Contents.json and refreshes; the user then runs the calculation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CANDIDATE_APP_DIRS = ["iwaraizar_fx_public", "Iwaraizar_FX"]


def _to_app_time(mt5_time: str) -> str:
    """'2024.01.03 12:00:00' -> '2024/01/03 12:00' (slash, minute precision)."""
    s = (mt5_time or "").strip().replace(".", "/").replace("-", "/")
    parts = s.split(" ")
    if len(parts) >= 2:
        hm = ":".join(parts[1].split(":")[:2])
        return f"{parts[0]} {hm}"
    return s


def to_contents_element(
    *,
    trades: list[dict],
    first_equity: float | None,
    title: str,
    parameter: str = "",
    modeling_quality: str = "",
    spread: str = "",
    mode: str = "MT5",
) -> dict:
    meta = {
        "mode": mode,
        "title": title,
        "FirstEquity": f"{first_equity:.2f}" if first_equity is not None else "0.00",
        "Parameter": parameter,
        "ModelingQuality": modeling_quality,
        "Spred": spread,
    }
    contents: list[dict] = [meta]
    for t in trades:
        contents.append({
            "FinishTime": _to_app_time(t["exit_time"]),
            "FinishPrice": str(t["exit_price"]),
            "Profit": t["profit"],
            "Balance": t["balance"],
            "title": title,
            "No": str(t["no"]),
            "Lot": t["lot"],
            "EntryTime": _to_app_time(t["entry_time"]),
            "EntryPrice": str(t["entry_price"]),
            "type": t["type"],
            "symbol": t["symbol"],
            "Swap": t["swap"],
            "Commission": t["commission"],
        })
    return {"Contents": contents}


def keepdata_dir(override: str | None = None) -> Path:
    """Locate the app's keepdata folder. Override wins; else known names; else scan %APPDATA%."""
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA", "")
    for name in CANDIDATE_APP_DIRS:
        d = Path(appdata) / name / "keepdata"
        if (d / "Contents.json").is_file():
            return d
    base = Path(appdata)
    if base.is_dir():
        for child in base.iterdir():
            if (child / "keepdata" / "Contents.json").is_file():
                return child / "keepdata"
    return Path(appdata) / CANDIDATE_APP_DIRS[0] / "keepdata"


def append_to_contents(element: dict, override: str | None = None, backup: bool = True) -> str:
    """Append one dataset element to keepdata/Contents.json (creating a .bak first)."""
    d = keepdata_dir(override)
    d.mkdir(parents=True, exist_ok=True)
    f = d / "Contents.json"
    data: list = []
    if f.is_file():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            data = []
        if not isinstance(data, list):
            data = [data]
        if backup:
            (d / "Contents.json.bak").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
    data.append(element)
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(f)
