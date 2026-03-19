# Terminal Claude Sync

Standalone terminal CLI with Feishu synchronization. Extracted from `remote-claude-code` for simplified deployment.

## Features

- **Native CLI Modes**: PTY (interactive) and Print (per-message process) modes
- **Feishu Synchronization**: Real-time sync to Feishu group chats
- **Dual-Channel Permissions**: Confirm sensitive operations from CLI or Feishu
- **Session Management**: Auto-create/disband Feishu group chats
- **Two Sync Modes**: `notify` (key events) or `sync` (full output)
- **Docker Support**: Dev Container configuration for isolated development

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Terminal CLI    │───►│ Bridge Server   │───►│ Feishu API      │
│ (交互界面)       │    │ (:8082)         │    │ (权限/同步)      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
        │                       │
        │ WebSocket             │ HTTP
        ▼                       ▼
┌─────────────────┐    ┌─────────────────┐
│ Native Client   │───►│ Claude CLI      │
│ (PTY/Print)     │    │ (原生进程)       │
└─────────────────┘    └─────────────────┘
```

## Quick Start

### Option A: Docker (Recommended)

#### 1. Setup Environment

```bash
cd .devcontainer
cp .env.example .env
# Edit .env with your credentials
```

#### 2. Start Container

```bash
docker-compose up -d
docker-compose exec app bash
```

#### 3. Run Inside Container

```bash
# Terminal 1: Start Bridge Server
python -m src.bridge

# Terminal 2: Start Terminal Client
python -m src.terminal_client
```

See [.devcontainer/README.md](.devcontainer/README.md) for detailed Docker setup.

### Option B: Local Installation

#### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

#### 2. Configure

Create `config.yaml` with your Feishu user open_id:

```yaml
terminal_session:
  user_open_id: "your_feishu_user_open_id"
```

#### 3. Set Environment Variables

```bash
export APP_ID="your_feishu_app_id"
export APP_SECRET="your_feishu_app_secret"
```

Or create a `.env` file:

```bash
cp .env.example .env
# Edit .env with your credentials
```

#### 4. Start Services

```bash
# Terminal 1: Start Bridge Server
python -m src.bridge

# Terminal 2: Start Terminal Client
python -m src.terminal_client --cli-mode print --sync-mode notify
```

## CLI Options

```
Terminal Client Options:
    --terminal-id      Terminal ID (auto-generated if not specified)
    --bridge-url       Bridge server URL (default: http://localhost:8082)
    --cli-mode         CLI mode: pty (interactive) or print (default: print)
    --sync-mode        Sync mode: notify or sync (default: notify)
    --user-open-id     Feishu user open_id
    --debug            Enable debug logging
```

## Modes

### Print Mode (Recommended)

Each message starts a new Claude process with `--print --output-format stream-json`. Best for:
- Simple question-answer workflows
- Lower resource usage
- Clear message boundaries

### PTY Mode

Interactive terminal emulation using `pty.openpty()`. Best for:
- Complex interactive sessions
- Real-time streaming output
- Full terminal experience

## Sync Modes

### Notify Mode (Default)

Only key events are synced to Feishu:
- Session start/stop
- Permission requests
- Errors

### Sync Mode

Full output synchronization:
- All responses
- Tool calls
- Status updates

## Dual-Channel Permissions

When Claude requests to use sensitive tools (Write, Edit, Bash):

1. CLI shows permission prompt
2. Feishu sends interactive card with Approve/Deny buttons
3. First response from either channel is used

This allows mobile confirmation via Feishu while working in terminal.

## Project Structure

```
terminal-claude-sync/
├── .devcontainer/           # Docker development environment
│   ├── Dockerfile           # Container image (Python 3.11 + Node 20)
│   ├── docker-compose.yml   # Container orchestration
│   ├── devcontainer.json    # VS Code Dev Containers config
│   ├── .env.example         # Environment variables template
│   └── README.md            # Docker setup guide
├── src/
│   ├── __main__.py          # Main entry point
│   ├── bridge/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   └── server.py        # Bridge HTTP/WebSocket server
│   ├── terminal_client/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   └── client.py        # Terminal CLI client
│   ├── native_claude_client.py  # Native Claude CLI wrapper
│   ├── terminal_session_manager.py  # Session management
│   ├── config.py            # Configuration loader
│   ├── protocol.py          # Event types
│   └── feishu_utils/
│       ├── __init__.py
│       ├── feishu_utils.py  # Feishu API helpers
│       └── card_builder.py  # Card message builder
├── data/
│   └── terminal_sessions.json   # Session persistence
├── config.yaml              # Configuration
├── requirements.txt
├── .env                     # Environment variables (not in git)
└── README.md
```

## API Endpoints

Bridge Server (`:8082`):

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/status` | GET | Detailed status |
| `/ws` | GET | WebSocket connection |
| `/terminal/create` | POST | Create terminal session |
| `/terminal/close` | POST | Close terminal session |
| `/terminal/sync` | POST | Sync output/status |
| `/permission/request` | POST | Permission request |
| `/permission/response` | POST | Permission response |

## Feishu App Requirements

Required permissions:
- `im:chat` - Create/manage chats
- `im:message` - Basic message permissions
- `im:message:send_as_bot` - Send messages as bot

Required events:
- `im.message.receive_v1` - Receive messages
- `im.chat.member.user_withdrawn_v1` - User leaves group
- `im.chat.disbanded_v1` - Group disbanded

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `APP_ID` | Feishu App ID | Yes |
| `APP_SECRET` | Feishu App Secret | Yes |
| `ANTHROPIC_AUTH_TOKEN` | Claude API Token | Yes |

## License

MIT