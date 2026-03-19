# Quick Start in Docker

本目录包含 Terminal Claude Sync 开发环境的 Docker 配置文件。

## 快速开始

### 1. 首次设置

运行配置脚本生成 `.env` 文件：

```bash
cd .devcontainer

# 交互式设置（推荐）
./setup_env.sh

# 或使用非交互式模式（生成默认配置）
./setup_env.sh --non-interactive
```

### 2. 启动开发容器

```bash
docker-compose up -d
```

### 3. 进入容器

```bash
docker-compose exec app bash
```

### 4. 在容器内运行

```bash
# 终端1：启动 Bridge Server
python -m src.bridge

# 终端2：启动 Terminal Client
python -m src.terminal_client
```

## 文件结构

```
.devcontainer/
├── Dockerfile              # 容器镜像定义
├── docker-compose.yml      # 容器编排配置
├── devcontainer.json       # VS Code Dev Containers 配置
├── setup_env.sh            # 环境配置脚本
├── .env.example            # 环境变量模板
├── .env                    # 实际环境变量（需生成，不提交到 Git）
└── README.md               # 本文件
```

## 环境变量配置

### .env 文件说明

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `UID` | 用户 ID（用于 Docker 权限） | 自动检测 |
| `GID` | 用户组 ID（用于 Docker 权限） | 自动检测 |
| `APP_ID` | 飞书应用 ID | **是** |
| `APP_SECRET` | 飞书应用 Secret | **是** |
| `ANTHROPIC_AUTH_TOKEN` | Claude API 认证 Token | **是** |
| `ANTHROPIC_BASE_URL` | API 基础 URL（代理用） | 否 |
| `BRIDGE_PORT` | Bridge 服务端口 | 否 (默认 8082) |

## VS Code Dev Containers

如果你使用 VS Code，可以直接打开项目并选择 "Reopen in Container"。

### 已安装扩展

- Python + Pylance
- Ruff (Linter)
- Git History + GitLens

## 使用方式

### 方式一：交互式设置

```bash
./setup_env.sh
```

脚本会提示您输入各项配置。

### 方式二：手动编辑 .env

复制模板并编辑：

```bash
cp .env.example .env
# 使用编辑器修改 .env
```

### 方式三：命令行直接设置

```bash
export APP_ID="your_app_id"
export APP_SECRET="your_app_secret"
export ANTHROPIC_AUTH_TOKEN="your_api_key"
docker-compose up -d
```

## 安全提示

- `.env` 文件包含敏感信息（API Key），已添加到 `.gitignore`
- 不要将 `.env` 提交到版本控制
- 定期轮换 API Key

## 故障排查

### 容器启动失败

检查 `.env` 文件是否存在：

```bash
ls -la .env
```

如果不存在，运行：

```bash
./setup_env.sh
```

### 端口冲突

如果 8082 端口被占用，修改 `.env` 中的 `BRIDGE_PORT`：

```bash
BRIDGE_PORT=8083
```

然后重启容器：

```bash
docker-compose down
docker-compose up -d
```

### 权限问题

确保 `setup_env.sh` 有执行权限：

```bash
chmod +x setup_env.sh
```

## 参考链接

- [Dev Containers 文档](https://containers.dev/)
- [Docker Compose 文档](https://docs.docker.com/compose/)
- [Claude Code 文档](https://claude.ai/code)
- [飞书开放平台](https://open.feishu.cn/)