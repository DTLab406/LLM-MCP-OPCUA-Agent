import asyncio
import json
import os
import sys
import traceback
from typing import List, Dict, Any

from openai import AsyncOpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from prompt_toolkit import PromptSession

# DeepSeek API 配置
API_KEY = "xxx"
BASE_URL = "https://api.deepseek.com"

#BASE_URL = "http://localhost:11434/v1"
#API_KEY = "ollama" # 随便填，不能为空

MAX_ITERATIONS = 10

client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)


def get_system_prompt() -> str:
    """
    构建结构化的系统提示词
    """
    prompt = f"""
你是一个专业的工业机器人控制与规划专家（Autonomous Agent）。 

【核心执行原则：严禁并行与跨步】
1. [cite_start]**严格顺序执行**：你必须严格按照"分析 -> 调用 -> 观察 -> 下一步"的逻辑循环。必须确保当前动作已经执行完成，才能进行下一个动作，不允许机械臂在运动中就执行下一个动作
2. **禁止超前规划**：在当前工具调用的结果（Tool Result）返回并被你解析之前，**严禁**尝试预测下一步的结果或连续发起不相关的后续指令。
3. **确认后再继续**：每一步操作后，必须根据工具返回的实际状态（如返回值、成功标识）来决定是否安全进入下一个步骤。

【你的核心职责】
1. 解析用户的自然语言指令，通过**多步推理**和**连续工具调用**来完成任务。 
2. 如果第一次工具调用没有达成目标，你必须**自主**尝试其他路径或工具，直到成功或确认无法执行。 
3. **不要**在每一步中间停下来询问用户，除非需要用户提供新信息或确认高风险操作。 

【常见任务指引】
- **寻找方法**: 如果 `list_methods` 返回空，请尝试递归查找。 
- **使能机器人**: 必须先确认连接成功，再执行使能，严禁在连接指令发出前就假设机器人已使能。 

【注意事项】
- 除非用户明确要求镜像模式，否则默认使用 parallel 模式利用内置标定。
- 严禁产生幻觉，只使用提供的工具。 
- 在执行运动指令前，务必检查参数安全。 
"""
    return prompt.strip()


def convert_tool_to_openai_format(tool) -> Dict[str, Any]:
    """将MCP工具定义转换为OpenAI兼容格式"""
    type_mapping = {
        "integer": "integer",
        "string": "string",
        "number": "number",
        "boolean": "boolean",
        "array": "array",
        "object": "object"
    }

    properties = {}
    required = []

    input_schema = tool.inputSchema or {}

    if isinstance(input_schema, dict):
        if 'properties' in input_schema:
            for param_name, param_info in input_schema['properties'].items():
                param_type = param_info.get('type', 'string')
                openai_type = type_mapping.get(param_type, 'string')

                properties[param_name] = {
                    "type": openai_type,
                    "description": param_info.get('description', f"{param_name} parameter")
                }
        if 'required' in input_schema:
            required = input_schema['required']

    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }
    }


# =================主逻辑=================

async def run_chat_loop(session: ClientSession, openai_tools: List[Dict]):
    """
    聊天循环 - 支持自动多步执行
    """
    # 初始化对话历史
    messages = [
        {"role": "system", "content": get_system_prompt()}
    ]
    prompt_session = PromptSession()

    print(f">>> 系统初始化完成。Agent 已就绪。")
    print(f">>> 请输入指令 (输入 'quit' 或 'exit' 退出):\n")

    while True:
        try:

            user_input = user_input.strip()

            if user_input.lower() in ['quit', 'exit', '退出']:
                print("正在关闭会话...")
                break

            if not user_input:
                continue

            messages.append({"role": "user", "content": user_input})

            step_count = 0
            while step_count < MAX_ITERATIONS:
                step_count += 1

                response = await client.chat.completions.create(
                    model="deepseek-chat",
                    messages=messages,
                    tools=openai_tools,
                    tool_choice="auto",
                    temperature=0.1 # 保持低随机性以确保逻辑严密
                )

                response_msg = response.choices[0].message
                messages.append(response_msg)

                if response_msg.tool_calls:
                    if response_msg.content:
                        print(
                            f"AI (Thinking Step {step_count}): {response_msg.content}")

                    print(f"\n>>> 正在执行工具调用 (Step {step_count})...")

                    for tool_call in response_msg.tool_calls:
                        func_name = tool_call.function.name
                        func_args_str = tool_call.function.arguments

                        try:
                            func_args = json.loads(func_args_str)
                            print(f"[Tool Call] {func_name}({func_args_str})")

                            result = await session.call_tool(func_name, arguments=func_args)

                            output_text = ""
                            if result.content and isinstance(result.content, list):
                                output_text = result.content[0].text
                            else:
                                output_text = str(result)

                            display_text = output_text if len(output_text) < 500 else output_text[:500] + "...(truncated)"
                            print(f"[Tool Result] => {display_text}")

                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": func_name,
                                "content": output_text
                            })

                        except Exception as e:
                            error_msg = f"Error executing {func_name}: {str(e)}"
                            print(f"{error_msg}")
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": func_name,
                                "content": error_msg
                            })

                    continue

        except Exception as e:
            print(f"Runtime Error: {str(e)}")
            traceback.print_exc()


async def main():
    """
    程序入口
    """
    possible_servers = ["opcua-mcp-server.py"]
    server_script = None

    for script in possible_servers:
        if os.path.exists(script):
            server_script = script
            break

    server_params = StdioServerParameters(
        command="python",
        args=[server_script],
        env=os.environ.copy()
    )

    print(f"=== 基于 LLM 的工业机器人语义交互系统 ===")
    print(f"正在连接 MCP 服务器: {server_script}...")

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools_result = await session.list_tools()
                available_tools = tools_result.tools

                print(f"检测到 {len(available_tools)} 个可用工具。")
                openai_tools = []
                for tool in available_tools:
                    openai_tools.append(convert_tool_to_openai_format(tool))

                await run_chat_loop(session, openai_tools)

    except FileNotFoundError:
        print(
            f"错误: 找不到 Python 解释器或服务器脚本 ({server_script})。请确保文件在当前目录下。")
    except Exception as e:
        print(f"连接致命错误: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    if sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())