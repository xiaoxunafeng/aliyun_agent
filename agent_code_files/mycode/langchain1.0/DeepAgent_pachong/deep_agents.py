import os
import asyncio
from langchain_openai import ChatOpenAI
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from dotenv import load_dotenv
from langchain_community.tools import TavilySearchResults

# 1. 配置 API Keys (实际使用建议写入环境变量)
load_dotenv(override=True)

# 2. 定义工具集合
# DeepAgent 默认会自动注入文件系统工具和规划工具，但为了明确工具定义，建议手动实例化
from langchain_community.tools import ReadFileTool, WriteFileTool, ShellTool

search_tool = TavilySearchResults(max_results=3)
read_tool = ReadFileTool(root_dir="./workspace")
write_tool = WriteFileTool(root_dir="./workspace")
shell_tool = ShellTool()

# 将工具实例放入列表
tools = [search_tool, read_tool, write_tool, shell_tool]

# 3. 初始化 LLM
# 建议使用推理能力强的模型，如 GPT-4o 或 Claude-3.5-Sonnet，以保证规划的准确性
llm = ChatOpenAI(model="gpt-4o", temperature=0)

# 4. 创建 Deep Agent
# path="." 表示让 Agent 将当前目录作为它的"文件系统"工作区
agent = create_deep_agent(   
    model=llm,
    tools=tools,
    backend=FilesystemBackend(root_dir="./workspace"),
)


async def main():
    print("🤖 DeepAgent 启动中...\n")

    # 5. 定义一个复杂的长程任务
    task = """
    请调研 'LangChain DeepAgent' 的最新功能。
    1. 在网络上搜索相关信息。
    2. 将核心功能点总结并写入一个名为 'deepagent_report.md' 的文件中。
    3. 读取该文件确认写入成功，并输出文件内容。
    """

    # 6. 运行 Agent
    # DeepAgent 基于 LangGraph，因此使用 .stream 或 .invoke
    async for event in agent.astream({"messages": [("user", task)]}):
        # 这里只打印关键步骤信息
        if "tools" in event:
            print(f"🛠️  调用工具: {event['tools']}")
        if "messages" in event:
            # 打印最新的回复内容
            last_msg = event["messages"][-1]
            if last_msg.content:
                print(f"🤖 Agent: {last_msg.content[:100]}...")  # 只打印前100字符预览

    print("\n✅ 任务结束。请检查 workspace/deepagent_report.md 文件。")


if __name__ == "__main__":
    # 创建工作目录
    os.makedirs("workspace", exist_ok=True)
    asyncio.run(main())