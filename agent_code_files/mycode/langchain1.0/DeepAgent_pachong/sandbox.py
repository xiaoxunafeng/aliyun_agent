from pathlib import Path
from typing import Dict, Any, Optional
import time
import os

from docker_backend import DockerBackend
import agent_config as config
from langchain_core.tools import tool


def _read_text_file(file_path: Path) -> str | None:
    """读取文本文件内容的辅助函数"""
    try:
        text = file_path.read_text(encoding="utf-8").strip()
        return text or None
    except OSError:
        return None

def _write_text_file(file_path: Path, content: str) -> bool:
    """写入文本文件内容的辅助函数"""
    try:
        file_path.write_text(content, encoding="utf-8")
        return True
    except OSError:
        return False

def _resolve_container_id(
    requested_container_id: str | None,
    workspace_path: Path,
) -> str | None:
    """解析容器 ID
    
    逻辑:
    1. 如果未指定 ID，返回 None (创建新容器)。
    2. 如果指定为 "auto"，直接读取 `agent_config.py` 中的 `docker_container_id` 变量。
    3. 如果指定了具体 ID，直接返回。
    """
    if requested_container_id is None:
        return None
    if requested_container_id != "auto":
        return requested_container_id
    
    # 改为从配置文件读取
    if config.docker_container_id and config.docker_container_id.strip():
        return config.docker_container_id.strip()
        
    return None

def should_persist_runtime_files(
    *,
    requested_container_id: str | None,
    use_existing_spider: bool,
    resume_from: str,
) -> bool:
    """判断是否需要持久化运行时文件 (如容器 ID)"""
    if requested_container_id == "auto":
        return True
    if use_existing_spider:
        return True
    if resume_from != "full":
        return True
    return False

def initialize_docker_backend(
    *,
    requested_container_id: str | None,
    persist_runtime_files: bool,
) -> DockerBackend:
    """初始化 Docker 后端环境
    
    思路梳理:
    1. **挂载配置**: 将本地工作区目录挂载到容器内，实现文件共享。
    2. **ID 解析**: 确定是复用旧容器还是创建新容器 (基于配置文件)。
    3. **尝试连接**: 
        - 尝试使用解析出的 ID 连接现有容器。
        - 如果连接失败 (容器已停止或不存在)，捕获异常并降级为创建全新的容器。
    4. **提示信息**: 如果成功启动且 ID 发生变化，提示用户更新 `agent_config.py`。
    
    Args:
        requested_container_id: 请求的容器 ID (None, "auto", 或具体 ID)
        persist_runtime_files: (保留参数，用于控制提示逻辑)
        
    Returns:
        已就绪的 DockerBackend 实例
    """
    print("\n2️⃣ 初始化 Docker 沙箱...")
    docker_volumes = {str(config.workspace_dir): {"bind": config.container_mount_path, "mode": "rw"}}
    resolved_container_id = _resolve_container_id(requested_container_id, config.workspace_dir)

    try:
        backend = DockerBackend(    
            image=config.docker_image,            # 使用配置中的 Docker 镜像
            container_id=resolved_container_id,   # 解析后的容器 ID (可能为 None)
            network_disabled=False,               # 禁用网络 (防止外部访问)
            memory_limit="1g",                    # 内存限制为 1GB
            cpu_quota=100000,                     # CPU 配额为 100ms (100000 微秒)
            auto_remove=False,                    # 不自动删除容器, 保留状态
            volumes=docker_volumes,               # 挂载本地工作区目录到容器内
            working_dir=config.container_mount_path,  # 设置容器内工作目录为挂载路径
        )
    except Exception as e:
        # 捕获异常, 说明容器不存在或已停止，则创建全新的容器
        if resolved_container_id:
            print(f"⚠️ 无法连接到容器 {resolved_container_id}: {e}")
            print("🔄 正在创建全新的 Docker 容器...")
        backend = DockerBackend(
            image=config.docker_image,
            container_id=None,
            network_disabled=False,
            memory_limit="1g",
            cpu_quota=100000,
            auto_remove=False,
            volumes=docker_volumes,
            working_dir=config.container_mount_path,
        )

    print(f"   ✅ Docker 容器已就绪: {backend.id[:12]}")
    
    # 逻辑变更：不再自动写入 docker_container_id.txt，而是提示用户修改配置文件
    if persist_runtime_files and backend.id != resolved_container_id:
        print(
            f"   💡 提示: 下次运行请更新 agent_config.py 中的 docker_container_id = \"{backend.id}\" 以复用此环境"
        )

    return backend

def create_execute_in_sandbox_tool(docker_backend: DockerBackend):
    """创建沙箱执行工具（闭包工厂）
    
    该函数返回一个绑定了 `docker_backend` 实例的 LangChain Tool。
    核心逻辑是： “外层函数负责接收环境（工具箱），内层函数负责干活（使用工具），最后把打包好的内层函数交出去。”
    """
    
    @tool
    async def execute_in_sandbox(code: str, timeout: int = 60) -> Dict[str, Any]:
        """在 Docker 沙箱中执行爬虫代码
        
        思路梳理:
        1. **代码上传**: 将生成的 Python 代码字符串写入 `spider.py` 并上传到容器工作目录。
        2. **环境检查**: 
            - 检查容器内是否安装了 `requests` 等必要库。
            - 如果缺失，自动执行 `pip install` 进行安装 (使用国内源或预置镜像可加速)。
        3. **代码执行**: 
            - 在容器内运行 `python spider.py`。
            - 捕获标准输出 (stdout) 和标准错误 (stderr)。
        4. **结果提取**:
            - 尝试从容器下载 `scraped_data.json` 数据文件。
            - 如果成功下载，将其保存到本地 `raw_data.json` 供后续处理。
        5. **输出截断**:
            - 为了防止 LLM 上下文溢出 (Context Window Explosion)，对过长的控制台输出进行截断 (只保留前 500 字符)。
        6. **错误处理**:
            - 捕获执行过程中的任何异常，返回结构化的错误信息。
        
        Args:
            code: 完整的 Python 爬虫代码
            timeout: 执行超时时间（秒）
        
        Returns:
            包含执行状态、输出预览、数据文件路径的字典
        """
        start_time = time.time()
        
        try:
            # 1. 上传代码文件
            upload_result = docker_backend.upload_files([
                ("spider.py", code.encode('utf-8'))
            ])
            
            if not upload_result or upload_result[0].error:
                return {
                    "success": False,
                    "error": "代码上传失败",
                    "exit_code": 1
                }
            
            # 2. 安装依赖 (如果需要)
            check_cmd = "pip show requests > /dev/null 2>&1"
            check_result = docker_backend.execute(check_cmd)
            
            if check_result.exit_code != 0:
                install_cmd = "pip install --no-cache-dir requests beautifulsoup4 lxml fake-useragent 2>&1"
                docker_backend.execute(install_cmd)
            
            # 3. 执行代码
            exec_result = docker_backend.execute(f"cd {docker_backend.working_dir} && python spider.py 2>&1")
            
            duration = time.time() - start_time
            
            # 4. 尝试下载数据文件
            scraped_data = None
            try:
                download_result = docker_backend.download_files(
                    [f"{docker_backend.working_dir}/scraped_data.json"]
                )
                if download_result and download_result[0].content:
                    scraped_data = download_result[0].content.decode('utf-8')
                    
                    # 将经过爬虫分析后得到的数据，保存到本地磁盘中
                    os.makedirs(config.workspace_dir, exist_ok=True)
                    with open(config.workspace_dir / "raw_data.json", "w", encoding="utf-8") as f:
                        f.write(scraped_data)
            except:
                pass
            
            # 5. 🔥 截断输出，避免上下文爆炸   
            output_preview = exec_result.output[:500] if exec_result.output else ""
            if len(exec_result.output) > 500:
                output_preview += f"\n... [截断 {len(exec_result.output) - 500} 字符]"
            
            return {
                "success": exec_result.exit_code == 0,       # 执行成功 (退出码为 0)
                "output_preview": output_preview,            # 只返回预览
                "exit_code": exec_result.exit_code,          # 退出码 (0 表示成功)
                "error": None if exec_result.exit_code == 0 else output_preview,  # 非 0 退出码时返回错误信息的预览
                "duration": duration,                        # 执行耗时 (秒)
                "data_saved": scraped_data is not None,      # 是否成功保存数据文件
                "data_file": "scraped_data.json" if scraped_data else None  # 数据文件路径 (如果有)
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)[:200],  # 截断错误信息
                "exit_code": 1,
                "duration": time.time() - start_time
            }

    # 返回内层函数
    return execute_in_sandbox

