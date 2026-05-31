print(4)

# 加载环境
from dotenv import load_dotenv

# 加载 .env 环境变量
load_dotenv(override=True)



# 使用init_chat_model初始化DeepSeek模型
from langchain.chat_models import init_chat_model

# 1. 初始化模型（自动识别供应商）
model = init_chat_model(
    "deepseek-chat",                # 指定DeepSeek的聊天模型
    model_provider="deepseek",      # 指定模型提供商为deepseek
)

# 一行代码切换模型，业务代码0改动
# model = init_chat_model("gpt-4o", model_provider="openai")
# model = init_chat_model("claude-3-5-sonnet", model_provider="anthropic")

question = "你好，请你介绍一下你自己。"
result = model.invoke(question)
print(result.content)




