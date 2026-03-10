# 🤖 LLM-MCP-OPCUA 工业机器人语义交互智能体

基于大语言模型 (LLM) 和 MCP 协议的工业机器人语义交互系统。通过 OPC UA 连接底层硬件，实现基于自然语言的单臂控制、双臂协同与接力搬运的自主任务执行。
本系统允许用户通过自然语言直接向工业机器人下发复杂任务，AI Agent 将自动进行任务拆解、环境感知与动作执行，并具备完整的安全校验机制。


# 🎥 演示视频 / Demo
![3102-ezgif com-optimize](https://github.com/user-attachments/assets/b79c8e41-ee55-4fdb-8b78-764432293eac)


# ✨ 核心特性

🧠 自主智能体循环 (Autonomous Agent Loop)
基于 DeepSeek / Ollama，支持最多 100 轮多步思考与执行。
内置 <thinking> 机制，自动区分合力搬运/接力协作与独立并行任务。

🔌 标准 MCP 架构
Client: 负责大语言模型交互、上下文管理与控制台高亮终端（基于 prompt_toolkit）。
Server (FastMCP): 封装了超过 15 个 OPC UA 操作工具，标准化的工具调用接口。

🏭 深度工业控制整合 (OPC UA)
支持节点读写、浏览、方法调用。
内置 Consul 服务发现，自动扫描并连接局域网内的机器人节点。

🤝 双臂协同与数学计算引擎
内置 A/B 机械臂双向标定参数（Offset Calibration）。

🛡️ 严格的安全与物理约束
强制使能检查、强制 Z+20mm 安全高度规范。
运动前坐标校验，避免运动中执行末端动作，严防物理越界。


# 🚀 快速开始

1. 环境准备
   
Python 3.9+
建议配置 Consul 用于服务发现。

工业机器人（或支持 OPC UA 的模拟器）。

2. 安装依赖
   
克隆仓库并安装必要的 Python 包：

pip install mcp opcua asyncua openai prompt_toolkit requests numpy

3. 配置参数

编辑 MCPClient.py 中的 API 配置（默认使用 DeepSeek，也可取消注释切换至本地 Ollama）：


API_KEY = "你的_DEEPSEEK_API_KEY"

BASE_URL = "https://api.deepseek.com"

#或者使用本地 Ollama

#BASE_URL = "http://localhost:11434/v1"

#API_KEY = "ollama"

如果你的 Consul 地址不同，请在终端设置环境变量，或直接修改 opcua-mcp-server.py：

export CONSUL_HOST="127.0.0.1"

export CONSUL_PORT="8500"

4. 运行系统

系统采用 stdio 方式进行 MCP 通信，客户端会自动拉起服务端，只需运行 Client 即可：


python MCPClient.py


# 💬 使用示例 / Example Prompts

在终端出现 User: 提示符后，你可以尝试输入以下自然语言指令：

场景 1：双臂协同搬运

"Robot A 和 Robot B 需要协同搬运一个长度为 100mm 的木块。物块中心点在A坐标系的 [300, 0, 150]。请规划它们的安全抓取路线并执行。"

场景 2：单臂独立任务

"让 Robot A 移动到 [250, 50, 200] 的位置，然后打开吸盘。"

场景 3：设备诊断

"检查一下当前 Consul 中发现了哪些可用的机械臂 OPC UA 节点，并读取 Robot A 的当前状态和坐标。"


# 🛠️ 可用工具列表 (MCP Tools)

MCP Server 为大模型提供了丰富的工业控制工具：

工具名称	描述

calculate_collaborative_pose	[核心] 计算双臂协同的防碰撞抓取位姿

execute_coordinated_movement	[核心] 执行多机器人协同运动规划

list_opcua_servers	从 Consul 缓存/刷新可用的 OPC UA 节点

read_opcua_node / write_opcua_node	读取/写入特定的 OPC UA 节点值

call_opcua_method	在指定对象节点上调用控制方法（如移动、夹取）

get_server_status	获取目标 OPC UA 服务器的运行状态与时间


# ⚠️ 安全警告 (Safety Warning)
真实硬件测试前，请务必在仿真环境中充分验证！
本项目的 AI 规划具有一定的非确定性，虽然已在 System Prompt 和 SpatialCalculator 中加入了限位保护和防碰撞逻辑，但在初次对接真实机械臂时，请务必手握急停按钮 (E-Stop)。
确保你的 OPC UA 网络处于受控的局域网中，避免安全漏洞。


# 📄 许可证 (License)
本项目采用 MIT 许可证 - 详情请查看 LICENSE 文件。
