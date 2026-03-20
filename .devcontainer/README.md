# Quick Start in Docker

本目录包含 Terminal Claude Sync 开发环境的 Docker 配置文件。

## 配置说明

Docker 容器通过卷挂载直接继承宿主机的环境配置：

- `~/.claude/*` → Claude 配置和凭证（只读）
- `~/.gitconfig` → Git 配置（只读）
- 项目目录 → 代码同步


## 快速开始

### 1. 启动开发容器

```bash
cd .devcontainer
docker-compose up -d
```

### 2. 进入容器

```bash
docker-compose exec app bash
```

### 3. 在容器内运行

```bash
# 终端1：启动 Bridge Server
python -m src.bridge

# 终端2：启动 Terminal Client
python -m src.terminal_client
```

## 文件结构

```
.devcontainer/
├── Dockerfile           # 容器镜像定义
├── docker-compose.yml   # 容器编排配置
├── devcontainer.json    # VS Code Dev Containers 配置
└── README.md            # 本文件
```

## 环境变量说明

容器继承宿主机的环境变量。在启动前，确保宿主机已配置：

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `APP_ID` | 飞书应用 ID | **是** |
| `APP_SECRET` | 飞书应用 Secret | **是** |
| `ANTHROPIC_AUTH_TOKEN` | Claude API 认证 Token | **是** |
| `ANTHROPIC_BASE_URL` | API 基础 URL（代理用） | 否 |
| `BRIDGE_PORT` | Bridge 服务端口 | 否 (默认 8082) |

### 配置方式

在宿主机创建 `~/.claude/.env` 或在项目根目录创建 `.env`：

```bash
# 宿主机执行
export APP_ID="your_app_id"
export APP_SECRET="your_app_secret"
export ANTHROPIC_AUTH_TOKEN="your_api_key"
```

或者使用 `config.yaml` 配置 `terminal_session.user_open_id`。

## VS Code Dev Containers

如果你使用 VS Code，可以直接打开项目并选择 "Reopen in Container"。

### 已安装扩展

- Python + Pylance
- Ruff (Linter)
- Git History + GitLens

## 故障排查

### Claude 认证问题

确保宿主机的 `~/.claude/` 目录存在且包含有效凭证：

```bash
ls -la ~/.claude/
```

### 端口冲突

如果 8082 端口被占用，可在 docker-compose.yml 中修改端口映射。

## 参考链接

- [Dev Containers 文档](https://containers.dev/)
- [Docker Compose 文档](https://docs.docker.com/compose/)
- [Claude Code 文档](https://claude.ai/code)
- [飞书开放平台](https://open.feishu.cn/)