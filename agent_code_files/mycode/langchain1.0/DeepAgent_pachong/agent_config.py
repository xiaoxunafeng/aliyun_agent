from pathlib import Path

# =============================================================================
# 基础配置 (User Configuration)
# =============================================================================
# 用户标识：用于区分多用户场景下的会话或权限（目前主要用于日志标识）
user_id: str = "default_user"

# 模型名称：指定用于代码生成和逻辑推理的大模型（如 deepseek-chat, gpt-4 等）
model_name: str = "deepseek-chat"

# 工作空间目录：本地用于存储生成的爬虫代码、运行日志和数据文件的根目录
# 该目录会自动映射到 Docker 容器内部

workspace_dir: Path = Path("./spider_workspace").resolve()

# =============================================================================
# Docker 沙箱配置 (Sandbox Configuration)
# =============================================================================
# 容器挂载路径：Docker 容器内部的工作目录路径
# 本地的 workspace_dir 会被挂载到此位置，确保文件读写同步
container_mount_path: str = "/workspace"

# 基础镜像：用于运行 Python 爬虫代码的 Docker 镜像
docker_image: str = "python:3.11-slim"

# 容器 ID：指定复用的 Docker 容器 ID
# - 如果指定了 ID：尝试连接该容器（需确保容器正在运行）
# - 配合 --container-id auto 参数可实现自动复用
docker_container_id: str = "5236cf3f3150fe26db0ea4d68e8986200f444f4b583aa4adaf6b73fa2a8e021e"

# 最大上下文 Token 数：防止对话历史过长超出模型限制
# 当超过此限制时，系统可能会进行记忆压缩或截断
max_context_tokens: int = 20000

# =============================================================================
# 初始化逻辑
# =============================================================================
# 自动创建工作目录：防止因目录不存在导致的 IO 错误
workspace_dir.mkdir(parents=True, exist_ok=True)
