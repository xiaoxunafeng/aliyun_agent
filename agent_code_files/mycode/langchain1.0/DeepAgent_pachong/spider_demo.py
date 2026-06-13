from dotenv import load_dotenv
import asyncio
import argparse
from datetime import datetime
import time
from typing import Any
from langchain_core.messages import ToolMessage, AIMessage, BaseMessage

from rich.console import Console
from rich.panel import Panel

import agent_config as config
from sandbox import initialize_docker_backend, DockerBackend, should_persist_runtime_files
from agent import build_agent

load_dotenv(override=True)

# Agent 配置
agent_config = {"configurable": {"thread_id": "demo_orchestrator"}}

# 定义供 LangGraph CLI 使用的全局 agent 变量
# LangGraph CLI 默认会寻找名为 'agent' 的变量，或者通过 graph=... 指定
# 这里我们构造一个 dummy agent，或者直接复用 build_agent 返回的图
# 由于 build_agent 需要 DockerBackend 依赖，而 LangGraph CLI 环境下无法动态传入 backend，
# 因此这里我们构建一个使用默认配置的 agent 实例。
try:
    # 尝试使用默认配置初始化 backend，这可能会启动 Docker 容器
    # 注意：在 LangGraph Studio 中频繁重启容器可能不是最佳实践
    # 更好的方式可能是使用 mock backend 或者持久化 backend

    _default_backend = initialize_docker_backend(
        requested_container_id="auto",
        persist_runtime_files=True
    )
    # build_agent 返回的是一个 CompiledStateGraph
    agent,sandbox = build_agent(_default_backend)
except Exception as e:
    print(f"Warning: Failed to initialize default agent for LangGraph CLI: {e}")
    agent = None

async def _run_fast_pipeline(
    *,
    docker_backend: DockerBackend,
    spider_relpath: str,
    resume_from: str,
    persist_runtime_files: bool,
    task: str,
) -> None:
    """快速执行管道 (非 Agent 模式)
    
    思路梳理:
    1. **跳过分析与生成**: 假设爬虫代码 (`spider.py`) 已经存在，直接运行。
    2. **执行爬虫**: 在 Docker 容器中执行 Python 脚本。
    3. **结果验证**:
        - 检查脚本退出码。
        - 检查数据文件 (`scraped_data.json`) 是否生成。
    4. **数据回传**: 将容器内的数据文件下载到本地 `raw_data.json`。
    5. **后续处理**: 
        - 调用 `clean_data` 进行数据清洗。
        - 调用 `validate_data` 进行质量验证。
    """
    start_time = time.time()
    console = Console()

    # 原始数据路径
    raw_data_path = config.workspace_dir / "raw_data.json"

    # 清洗后数据路径
    cleaned_data_path = config.workspace_dir / "data_cleaned.json"

    if resume_from in {"run", "clean"} and resume_from != "clean":
        # 1. 执行爬虫 
        exec_result = docker_backend.execute(
            f"cd {config.container_mount_path} && python {spider_relpath} 2>&1"
        )

        # 检查爬虫执行是否成功
        if exec_result.exit_code != 0:
            output_preview = (exec_result.output or "")[:800]
            console.print(
                Panel(
                    output_preview or "No output",
                    title="[bold red]❌ Spider 执行失败[/bold red]",
                    border_style="red",
                )
            )
            return

        # 2. 检查数据文件
        data_file = "scraped_data.json"
        exists_result = docker_backend.execute(
            f"cd {config.container_mount_path} && test -f {data_file}"
        )
        if exists_result.exit_code != 0:
            # 尝试猜测文件名 (取最新的 json 文件)
            guess_result = docker_backend.execute(
                f"cd {config.container_mount_path} && ls -t *.json 2>/dev/null | head -n 1"
            )
            guessed = (guess_result.output or "").strip()
            if guessed:
                data_file = guessed

        # 构建容器内数据文件路径
        data_file_path = (
            data_file if data_file.startswith("/") else f"{config.container_mount_path}/{data_file}"
        )
        
        # 3. 下载数据
        download_result = docker_backend.download_files([data_file_path])
        if not download_result or download_result[0].error or not download_result[0].content:
            json_list_result = docker_backend.execute(
                f"cd {config.container_mount_path} && ls -la *.json 2>/dev/null | head -n 20"
            )
            json_list_preview = (json_list_result.output or "").strip()
            console.print(
                Panel(
                    "\n".join(
                        [
                            f"无法下载数据文件: {data_file_path}",
                            "容器内 /workspace 的 JSON 文件列表(前20行):",
                            json_list_preview or "(empty)",
                        ]
                    ),
                    title="[bold red]❌ 数据文件缺失[/bold red]",
                    border_style="red",
                )
            )
            return

        raw_data_path.write_text(
            download_result[0].content.decode("utf-8", errors="replace"),
            encoding="utf-8",
        )

    # 5. 数据处理 (调用工具进行数据处理)
    if resume_from in {"run", "clean"}:
        # 4. 数据处理 (调用工具进行数据处理)
        # 注意：这里我们手动调用工具，模拟 Agent 的行为
        from tools import clean_data, validate_data
        
        console.print("[bold blue]开始数据清洗...[/bold blue]")
        cleaned_json = await clean_data.ainvoke({"raw_data": str(raw_data_path)})
        
        console.print("[bold blue]开始数据验证...[/bold blue]")
        validation = await validate_data.ainvoke({"data": cleaned_json, "required_fields": ["title", "url"]})
        
        console.print(Panel(str(validation), title="数据验证结果", border_style="green"))

    duration = time.time() - start_time
    console.print(f"\n[bold green]✅ 快速流程完成! 耗时: {duration:.2f}s[/bold green]")


async def main(task: str, run_options: dict[str, Any] | None = None):
    """主程序入口
    
    思路梳理:
    1. **参数解析**: 处理命令行参数，确定运行模式 (完整流程 vs 快速流程)。
    2. **环境初始化**: 
        - 决定是否持久化运行时文件。
        - 初始化 Docker 后端 (连接或创建容器)。
    3. **构建 Agent**: 创建 LangGraph 智能体图。
    4. **模式分发**:
        - 如果指定了 `--fast` 或 `--resume-from`，进入 `_run_fast_pipeline` 快速通道。
        - 否则，进入标准的 Agent 交互循环。
    5. **事件流处理**:
        - 监听 Agent 的思考过程 (`astream`)。
        - 解析不同类型的事件 (工具调用、子智能体返回、最终回复)。
        - 使用 Rich 库美化控制台输出。
    """
    run_options = run_options or {}
    requested_container_id = run_options.get("container_id", config.docker_container_id)
    use_existing_spider = bool(run_options.get("use_existing_spider", False))
    resume_from = run_options.get("resume_from", "full")
    spider_relpath = run_options.get("spider_relpath", "spider.py")

    # 3. 确定是否持久化运行时文件
    persist_runtime_files = should_persist_runtime_files(
        requested_container_id=requested_container_id,
        use_existing_spider=use_existing_spider,
        resume_from=resume_from,
    )

    # 1. 初始化 Docker 环境
    docker_backend = initialize_docker_backend(
        requested_container_id=requested_container_id,
        persist_runtime_files=persist_runtime_files,
    )
    
    # 2. 构建智能体
    agent, _sandbox_tool = build_agent(docker_backend)

    # 3. 快速通道 (复用已有代码)
    if use_existing_spider and resume_from in {"run", "clean"}:
        await _run_fast_pipeline(
            docker_backend=docker_backend,
            spider_relpath=spider_relpath,
            resume_from=resume_from,
            persist_runtime_files=persist_runtime_files,
            task=task,
        )
        return

    console = Console()
    console.print(f"\n[bold green]任务指令:[/bold green] {task}\n")

    step = 0
    try:
        # 4. Agent 执行循环
        print("DEBUG: Starting agent.astream loop...")
        async for event in agent.astream({"messages": [("user", task)]}, config=agent_config):
            print(f"DEBUG: Received event keys: {list(event.keys())}")
            step += 1
            for node_name, node_data in event.items():
                if node_data is None:
                    continue

                if "messages" in node_data:
                    msgs = node_data["messages"]
                    # 确保是列表
                    if not isinstance(msgs, list):
                        msgs = [msgs]

                    for msg in msgs:
                        # 0. 过滤非消息对象
                        if not isinstance(msg, BaseMessage):
                            continue

                        # 1. 检测工具调用 (期望看到 'task' 工具)
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                tool_name = tc['name']
                                tool_args = tc['args']

                                if tool_name == "task":
                                    # Sub-Agent 调用
                                    assignee = tool_args.get('assignee') or tool_args.get('subagent_type', 'unknown')
                                    content = tool_args.get('content') or tool_args.get('description', '')
                                    console.print(
                                        Panel(
                                            f"Assignee: {assignee}\nContent: {content}",
                                            title=f"[bold cyan]🔄 调用子智能体 (Node: {node_name})[/bold cyan]",
                                            border_style="cyan"
                                        )
                                    )
                                else:
                                    console.print(f"[bold cyan]🔧 {node_name} 调用工具:[/bold cyan] {tool_name}")
                                    console.print(f"[dim]参数: {tool_args}[/dim]")

                        # 2. 检测工具输出 (Sub-Agent 的返回结果)
                        elif isinstance(msg, ToolMessage):
                            if msg.name == "task":
                                # Sub-Agent 完成任务返回
                                panel = Panel(
                                    msg.content,
                                    title=f"[bold magenta]Sub-Agent 完成任务 (Node: {node_name})[/bold magenta]",
                                    border_style="magenta"
                                )
                                console.print(panel)
                            else:
                                console.print(f"[dim]Tool Output ({msg.name}): {msg.content[:100]}...[/dim]")

                        # 3. 检测 AI 最终回复
                        elif msg.content and not msg.tool_calls:
                            title = f"[bold green]Agent 回复 (Node: {node_name})[/bold green]"
                            console.print(Panel(msg.content, title=title, border_style="green"))

    except KeyboardInterrupt:
        console.print("\n[bold yellow]用户中断任务[/bold yellow]")
    except Exception as e:
        console.print(f"\n[bold red]❌ 发生错误: {e}[/bold red]")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--task",
        type=str,
        default="分析 https://movie.douban.com/网站， 并生成爬虫代码后，爬取首页里的电影信息和链接即可，其他的数据不用爬取！",
    )
        
    parser.add_argument(
        "--container-id",
        type=str,
        default=None,
        help="指定复用的 Docker 容器 ID；传 auto 则从 spider_workspace/docker_container_id.txt 读取",
    )
    parser.add_argument(
        "--resume-from",
        type=str,
        choices=["full", "run", "clean"],
        default="full",
    )
    parser.add_argument("--use-existing-spider", action="store_true")
    parser.add_argument(
        "--spider-relpath",
        type=str,
        default="spider.py",
        help="容器内 /workspace 下的脚本相对路径 (默认 spider.py)",
    )
    parser.add_argument("--fast", action="store_true")

    args = parser.parse_args()
    if args.fast:
        args.use_existing_spider = True
        args.resume_from = "run"
        if args.container_id is None:
            args.container_id = "auto"

    options = {
        "container_id": args.container_id if args.container_id is not None else config.docker_container_id,
        "resume_from": args.resume_from,
        "use_existing_spider": args.use_existing_spider,
        "spider_relpath": args.spider_relpath,
    }
    asyncio.run(main(args.task, options))
