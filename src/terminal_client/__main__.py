"""
Terminal Client Module

Run with: python -m src.terminal_client
"""
from src.terminal_client.client import TerminalClient, main

__all__ = ["TerminalClient", "main"]


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())