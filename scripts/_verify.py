"""Quick local verification: import server, detect MT5, list a few EAs."""
import asyncio

from mt5_mcp_server import server as s


def main() -> None:
    info = s.mt5_info()
    print("MT5_INFO:", info.model_dump_json())

    eas = s.list_eas("moving")
    print("EAS(moving):", [e.rel_path for e in eas])
    print("MA_sample_present:", any("Moving Average" in e.rel_path for e in eas))

    # list registered MCP tools (async API)
    tools = asyncio.run(s.mcp.list_tools())
    print("TOOLS:", [t.name for t in tools])


if __name__ == "__main__":
    main()
