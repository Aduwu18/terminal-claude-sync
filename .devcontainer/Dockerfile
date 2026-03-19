# ==================================================================
# Terminal Claude Sync Development Environment
# Optimized for: Claude CLI + Feishu Integration
# ==================================================================
FROM python:3.11-slim

ARG USERNAME=developer
ARG USER_UID=1000
ARG USER_GID=$USER_UID

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# --- 1. 基础换源与必备系统组件安装 ---
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends \
    sudo git curl wget jq iputils-ping ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# --- 2. 创建用户（处理 ID 冲突）---
RUN if getent group $USER_GID; then groupdel $(getent group $USER_GID | cut -d: -f1); fi && \
    if getent passwd $USER_UID; then userdel -f $(getent passwd $USER_UID | cut -d: -f1); fi && \
    groupadd --gid $USER_GID $USERNAME && \
    useradd --uid $USER_UID --gid $USER_GID -m $USERNAME && \
    echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME

# --- 3. 安装 Node.js 与 Claude Code ---
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    npm config set registry https://registry.npmmirror.com && \
    npm install -g @anthropic-ai/claude-code && \
    rm -rf /var/lib/apt/lists/*

# --- 4. Python 配置 ---
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set global.trusted-host mirrors.aliyun.com

# --- 5. 设置用户环境 ---
USER $USERNAME
WORKDIR /app

# --- 6. 默认启动命令 ---
CMD ["/bin/bash"]