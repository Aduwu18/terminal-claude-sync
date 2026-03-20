# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Terminal Claude Sync is a Python-based CLI tool that wraps the native `claude` CLI and synchronizes terminal sessions with Feishu (飞书) group chats. It enables dual-channel permission confirmation from both the terminal and Feishu mobile app.

## Core Commands

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Start bridge server (required first)
python -m src.bridge

# Start terminal client (print mode - recommended)
python -m src.terminal_client --cli-mode print --sync-mode notify

# Start terminal client (PTY mode - interactive)
python -m src.terminal_client --cli-mode pty --sync-mode notify

# Run with debug logging
python -m src.terminal_client --debug
```

### Docker Development

```bash
cd .devcontainer

# Start container (mounts host credentials)
docker-compose up -d
docker-compose exec app bash

# Inside container
python -m src.bridge           # Terminal 1
python -m src.terminal_client  # Terminal 2
```

## Required Configuration

### Environment Variables

```bash
export APP_ID="your_feishu_app_id"
export APP_SECRET="your_feishu_app_secret"
```

Or use `.env` file (auto-loaded via `python-dotenv`).

### config.yaml

- `terminal_session.user_open_id`: Your Feishu user open_id (REQUIRED)

## Architecture

```
Terminal CLI ──WebSocket──► Bridge Server ──HTTP──► Feishu API
      │                         │
      │                         │
      ▼                         ▼
Native Claude CLI         Session Manager
(PTY/Print modes)         (群聊创建/解散)
```

### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| Bridge Server | `src/bridge/server.py` | HTTP/WebSocket server coordinating CLI ↔ Feishu |
| Terminal Client | `src/terminal_client/client.py` | CLI interface for user interaction |
| Native Client | `src/native_claude_client.py` | Wraps `claude` CLI in PTY or Print mode |
| Session Manager | `src/terminal_session_manager.py` | Manages Feishu group chats for terminals |
| Feishu Utils | `src/feishu_utils/` | API wrappers and card message builders |

### Two CLI Modes

1. **Print Mode** (default): Each message spawns a new `claude --print --output-format stream-json` process. More stable, clear message boundaries.
2. **PTY Mode**: Interactive terminal emulation using `pty.openpty()`. Full terminal experience but more complex.

### Dual-Channel Permissions

When Claude requests sensitive tools (Write, Edit, Bash):
1. CLI shows permission prompt
2. Feishu sends interactive card with Approve/Deny buttons
3. First response from either channel is used

This enables mobile confirmation via Feishu while working in terminal.

## Feishu App Requirements

Required permissions:
- `im:chat` - Create/manage chats
- `im:message` - Basic message permissions
- `im:message:send_as_bot` - Send messages as bot

Required events:
- `im.message.receive_v1` - Receive messages
- `im.chat.member.user_withdrawn_v1` - User leaves group
- `im.chat.disbanded_v1` - Group disbanded

## Bridge Server Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/status` | GET | Detailed status with active sessions |
| `/ws` | GET | WebSocket connection (requires `?terminal_id=`) |
| `/terminal/create` | POST | Create terminal session + Feishu group |
| `/terminal/close` | POST | Close session + disband group |
| `/terminal/sync` | POST | Sync output/status to Feishu |
| `/permission/request` | POST | Request permission from Feishu |
| `/permission/response` | POST | Permission response from Feishu |

## Data Persistence

- Session data stored in `data/terminal_sessions.json`
- Auto-creates/disbands Feishu group chats on session start/stop
- Group naming: `{group_name_prefix} {hostname}` (default: "💻 Terminal {hostname}")

## Docker Configuration

Located in `.devcontainer/`:

| File | Purpose |
|------|---------|
| `Dockerfile` | Python 3.11 + Node.js 20 + Claude Code |
| `docker-compose.yml` | Container orchestration with volume mounts |
| `devcontainer.json` | VS Code Dev Containers configuration |

Note: Docker mounts your host environment (read-only), inheriting `~/.claude` and `~/.gitconfig`.

- Project code: `..:/app/terminal-claude-sync`
- Claude config: `~/.claude/*` (read-only)
- Git config: `~/.gitconfig` (read-only)

## Code Conventions

- Async/await throughout - all I/O operations are async
- Global singleton pattern for managers (`get_bridge_server()`, `get_terminal_session_manager()`)
- Dataclasses for data structures (`TerminalSession`, `NativeEvent`)
- Feishu cards built via `CardBuilder` class with fluent API
- Chinese comments in source files - maintain bilingual documentation