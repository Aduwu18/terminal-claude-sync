"""
Bridge Server Module

Run with: python -m src.bridge
"""
from src.bridge.server import run_bridge_server, get_bridge_server

__all__ = ["run_bridge_server", "get_bridge_server"]


async def main():
    """Main entry point for bridge server."""
    await run_bridge_server()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())