"""
Terminal Claude Sync

Standalone terminal CLI with Feishu synchronization.

Usage:
    python -m src                    # Show help
    python -m src.bridge             # Start bridge server
    python -m src.terminal_client    # Start terminal client
"""
import asyncio
import sys


def print_help():
    """Print help message."""
    print("""
Terminal Claude Sync - Standalone terminal CLI with Feishu synchronization

Usage:
    python -m src.bridge             Start bridge server
    python -m src.terminal_client    Start terminal client

Terminal Client Options:
    --terminal-id      Terminal ID (auto-generated if not specified)
    --bridge-url       Bridge server URL (default: http://localhost:8082)
    --cli-mode         CLI mode: pty (interactive) or print (default: print)
    --sync-mode        Sync mode: notify or sync (default: notify)
    --user-open-id     Feishu user open_id
    --debug            Enable debug logging

Examples:
    # Start bridge server (in one terminal)
    python -m src.bridge

    # Start terminal client (in another terminal)
    python -m src.terminal_client --cli-mode print --sync-mode notify

    # With debug logging
    python -m src.terminal_client --debug
""")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print_help()
        sys.exit(0)

    module = sys.argv[1]

    if module == "bridge":
        from src.bridge import main as bridge_main
        asyncio.run(bridge_main())
    elif module == "terminal_client" or module == "terminal":
        from src.terminal_client import main as terminal_main
        asyncio.run(terminal_main())
    elif module in ["-h", "--help", "help"]:
        print_help()
    else:
        print(f"Unknown module: {module}")
        print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()