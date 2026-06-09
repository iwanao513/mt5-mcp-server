"""Quick local verification: detect MT5(s), list EAs, list tools, target a specific install."""
import asyncio

from mt5_mcp_server import server as s


def main() -> None:
    tools = asyncio.run(s.mcp.list_tools())
    print("TOOLS:", [t.name for t in tools])

    terms = s.list_mt5_terminals()
    print(f"TERMINALS: {len(terms)}")
    for t in terms[:10]:
        df = (t.data_folder or "")[-12:]
        print(f"  - {t.terminal_path}  | data ...{df} | EAs {t.experts_count}")

    info = s.mt5_info()  # default
    print("DEFAULT mt5_info:", info.install_dir, "| EAs", info.experts_count, "| running", info.is_running)

    # target a specific install explicitly by path
    info2 = s.mt5_info(terminal_path=r"C:\Program Files\MetaTrader 5")
    print("EXPLICIT mt5_info:", info2.install_dir, "| EAs", info2.experts_count)

    eas = s.list_eas("moving")
    print("EAS(moving):", [e.rel_path for e in eas])


if __name__ == "__main__":
    main()
