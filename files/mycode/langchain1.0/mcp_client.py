import asyncio
import os
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from dotenv import load_dotenv
load_dotenv(override=True)


# 自定义本地工具（与 MCP 工具混合使用）
@tool
def local_calculator(expression: str) -> str:
    """执行复杂的数学表达式计算"""
    try:
        # 安全 eval，仅允许数学运算
        result = eval(expression, {"__builtins__": {}}, {})
        return f"计算结果: {result}"
    except Exception as e:
        return f"计算错误: {str(e)}"


async def create_mcp_agent():
    """创建集成 MCP 的 Agent"""

    # 1. 初始化 MCP 客户端，只连接本地 MCP 服务器
    # 获取当前文件所在目录的绝对路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    mcp_server_path = os.path.join(current_dir, "mcp_server.py")

    mcp_client = MultiServerMCPClient(
        {
            # 本地 Python MCP 服务器（stdio 传输）
            "math": {
                "transport": "stdio",
                "command": "python",
                "args": [mcp_server_path],  # 使用绝对路径
            },
            # 如果需要其他服务器，可以在这里添加
            # 注意：只添加确实在运行的服务器，否则会导致连接失败
        }
    )

    # 2. 异步获取所有 MCP 工具（关键步骤）
    print("🔄 正在连接 MCP 服务器并加载工具...")
    try:
        mcp_tools = await mcp_client.get_tools()
        print(f"✅ 成功加载 {len(mcp_tools)} 个 MCP 工具: {[t.name for t in mcp_tools]}")
    except Exception as e:
        print(f"❌ 加载 MCP 工具失败: {e}")
        print("⚠️  将只使用本地工具")
        mcp_tools = []

    # 3. 合并本地工具和 MCP 工具
    all_tools = [local_calculator] + mcp_tools
    print(f"✅ 使用 {len(all_tools)} 个工具: {[t.name for t in all_tools]}")

    # 4. 初始化 LLM（支持 OpenAI 兼容接口）
    llm = ChatOpenAI(
        model="gpt-4o",
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=0,  # 工具调用需低随机性
    )

    # 5. 使用 LangChain 1.0 的 create_agent 创建智能体
    # 注意：1.0 版本无需 AgentExecutor，直接返回可调用对象
    agent = create_agent(
        model=llm,
        tools=all_tools,
        system_prompt="""你是一个强大的 AI 助手，可以使用以下工具：
        1. MathServer 提供的 add/multiply/power 工具进行精确数学运算
        2. local_calculator 处理复杂表达式
        3. weather 工具查询实时天气
        4. amap 工具提供地图服务

        重要原则：
        - 优先使用专用工具而非本地计算
        - 工具调用后需整理结果并自然回答
        - 若工具调用失败，尝试替代方案"""
    )

    return agent, mcp_client


async def main():
    """主执行函数"""

    # 创建 Agent
    agent, mcp_client = await create_mcp_agent()

    # 测试用例集合
    test_cases = [
        {
            "name": "MCP加法工具",
            "query": "计算 123.45 + 678.90，使用 MCP 工具"
        },
        {
            "name": "MCP幂运算",
            "query": "计算 2 的 10 次方是多少？"
        },
        {
            "name": "混合计算",
            "query": "先计算 3.5 × 4，然后对结果进行平方"
        },
        {
            "name": "本地工具",
            "query": "用本地计算器计算 (10+5)*2/3"
        }
    ]

    print("\n" + "=" * 60)
    print("LangChain 1.0 MCP Agent 测试开始")
    print("=" * 60)

    for case in test_cases:
        print(f"\n【测试】{case['name']}")
        print(f"问题: {case['query']}")

        try:
            # 执行 Agent（1.0 版本使用 invoke/ainvoke）
            result = await agent.ainvoke({
                "messages": [{"role": "user", "content": case['query']}]
            })

            # 提取最终结果和工具调用信息
            messages = result["messages"]
            final_message = messages[-1]

            # 统计工具调用次数（查找所有 AIMessage 中的 tool_calls）
            tool_call_count = 0
            tool_names = []
            for msg in messages:
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    tool_call_count += len(msg.tool_calls)
                    tool_names.extend([tc['name'] for tc in msg.tool_calls])

            print(f"回答: {final_message.content}")
            print(f"工具调用次数: {tool_call_count}")
            if tool_names:
                print(f"调用的工具: {', '.join(tool_names)}")

            # 调试信息：显示所有消息类型
            if tool_call_count == 0:
                print(f"⚠️  调试信息：消息数量 = {len(messages)}")
                for i, msg in enumerate(messages):
                    print(f"  消息 {i}: {type(msg).__name__}")

        except Exception as e:
            print(f"❌ 执行失败: {str(e)}")
            import traceback
            traceback.print_exc()

    # 关闭 MCP 客户端连接
    if mcp_client is not None:
        print("\n🔄 正在关闭 MCP 连接...")
        try:
            # MultiServerMCPClient 使用 cleanup() 而不是 close()
            await mcp_client.cleanup()
            print("✅ MCP 连接已关闭")
        except AttributeError:
            # 如果没有 cleanup 方法，尝试其他方法
            print("⚠️  MCP 客户端无需手动关闭")
    else:
        print("\n✅ 无需关闭 MCP 连接（未使用 MCP 客户端）")


if __name__ == "__main__":
    # 运行异步主函数
    asyncio.run(main())