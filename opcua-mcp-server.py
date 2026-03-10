from mcp.server.fastmcp import FastMCP, Context
from opcua import Client, ua
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, List, Any, Optional
import asyncio
import os
import json
import requests
from opcua.ua import NodeClass
import logging
from datetime import datetime
import numpy as np
import copy

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Consul配置
CONSUL_HOST = os.getenv("CONSUL_HOST", "")
CONSUL_PORT = os.getenv("CONSUL_PORT", 8500)
CONSUL_BASE_URL = f"http://{CONSUL_HOST}:{CONSUL_PORT}/v1"

class OPCUAClientManager:

    def __init__(self):
        self.clients: Dict[str, Dict] = {}
        self.server_info: Dict[str, Dict] = {}
        self.consul_services_cache = None
        self.cache_time = None
        self.cache_duration = 30  # 缓存30秒

    async def discover_servers_from_consul(self):

        try:
            logger.info(f"正在扫描 Consul @ {CONSUL_BASE_URL} ...")
            resp = requests.get(f"{CONSUL_BASE_URL}/catalog/services", timeout=5)
            if resp.status_code != 200:
                logger.warning(f"无法从Consul获取服务列表: {resp.status_code}")
                return {}

            all_service_names = resp.json().keys()
            discovered_servers = {}

            for s_name in all_service_names:
                inst_resp = requests.get(f"{CONSUL_BASE_URL}/catalog/service/{s_name}", timeout=5)
                if inst_resp.status_code != 200: continue

                instances = inst_resp.json()
                for inst in instances:
                    tags = inst.get('ServiceTags', [])
                    if 'opcua' in [t.lower() for t in tags]:
                        addr = inst.get('ServiceAddress')
                        port = inst.get('ServicePort')
                        s_id = inst.get('ServiceID')
                        url = f"opc.tcp://{addr}:{port}"

                        discovered_servers[url] = {
                            'id': s_id,
                            'name': s_name,
                            'url': url,
                            'tags': tags,
                            'node': inst.get('Node'),
                            'discovery_time': datetime.now().isoformat()
                        }
                        logger.info(f"发现机械臂节点: {s_id} 地址: {url}")

            self.server_info.update(discovered_servers)
            return discovered_servers
        except Exception as e:
            logger.error(f"从Consul发现服务器失败: {e}")

    async def get_or_create_client(self, server_url: str) -> Optional[Client]:
        try:
            if server_url in self.clients:
                client_info = self.clients[server_url]
                client = client_info['client']
                try:
                    root = client.get_root_node()
                    root.get_children()

                    self.clients[server_url]['last_used'] = datetime.now()
                    return client

                except Exception:

                    logger.info(f"OPC UA客户端连接已断开，重新连接: {server_url}")
                    try:
                        await asyncio.to_thread(client.disconnect)
                    except:
                        pass

            logger.info(f"创建新的OPC UA客户端连接: {server_url}")
            client = Client(server_url)

            await asyncio.to_thread(client.connect)

            self.clients[server_url] = {
                'client': client,
                'last_used': datetime.now(),
                'created_at': datetime.now(),
                'server_url': server_url
            }

            if server_url not in self.server_info:
                self.server_info[server_url] = {
                    'id': f"manual_{server_url}",
                    'name': f"OPC UA Server at {server_url}",
                    'url': server_url,
                    'discovered_from': 'manual',
                    'discovery_time': datetime.now().isoformat(),
                    'service_type': 'opcua'
                }

            logger.info(f"成功连接到OPC UA服务器: {server_url}")
            return client

        except Exception as e:
            logger.error(f"连接OPC UA服务器失败 {server_url}: {e}")
            return None

    async def disconnect_client(self, server_url: str):

        if server_url in self.clients:
            try:
                client = self.clients[server_url]['client']
                await asyncio.to_thread(client.disconnect)
                logger.info(f"已断开OPC UA服务器连接: {server_url}")
            except Exception as e:
                logger.error(f"断开连接失败 {server_url}: {e}")
            finally:
                del self.clients[server_url]

    async def disconnect_all(self):

        disconnect_tasks = []
        for server_url in list(self.clients.keys()):
            disconnect_tasks.append(self.disconnect_client(server_url))

        if disconnect_tasks:
            await asyncio.gather(*disconnect_tasks, return_exceptions=True)

    def get_available_servers(self) -> List[Dict]:

        servers = []

        for server_url, info in self.server_info.items():
            server = info.copy()
            server['connected'] = server_url in self.clients
            server['server_url'] = server_url
            servers.append(server)

        return servers

client_manager = OPCUAClientManager()

@asynccontextmanager
async def opcua_lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """处理MCP服务器生命周期"""
    try:
        logger.info("正在从Consul发现所有注册的OPC UA服务器...")
        discovered_servers = await client_manager.discover_servers_from_consul()
        logger.info(f"发现 {len(discovered_servers)} 个OPC UA服务器")

        yield {"opcua_client_manager": client_manager}

    finally:
        logger.info("正在断开所有OPC UA服务器连接...")
        await client_manager.disconnect_all()
        logger.info("所有连接已断开")

mcp = FastMCP("OPCUA-Control-Multi", lifespan=opcua_lifespan)

# 工具：列出所有可用的OPC UA服务器
@mcp.tool()
async def list_opcua_servers(ctx: Context, force_refresh: bool = False) -> str:

    try:
        if force_refresh:
            client_manager.consul_services_cache = None
            await client_manager.discover_servers_from_consul()

        servers = client_manager.get_available_servers()

        result = {
            "total_servers": len(servers),
            "connected_servers": len(client_manager.clients),
            "servers": servers
        }

        formatted = f"可用OPC UA服务器 ({len(servers)} 个):\n\n"
        for i, server in enumerate(servers, 1):
            formatted += f"{i}. {server.get('name', '未知服务器')}\n"
            formatted += f"   地址: {server['server_url']}\n"
            formatted += f"   状态: {'已连接' if server['connected'] else '未连接'}\n"
            formatted += f"   来源: {server.get('discovered_from', '未知')}\n"
            if 'node' in server and server['node']:
                formatted += f"   节点: {server['node']}\n"
            if 'tags' in server and server['tags']:
                formatted += f"   标签: {', '.join(server['tags'])}\n"
            formatted += "\n"

        return formatted

    except Exception as e:
        return f"获取服务器列表失败: {str(e)}"

# 工具：读取OPC UA节点的值
@mcp.tool()
async def read_opcua_node(server_url: str, node_id: str, ctx: Context) -> str:

    try:
        client = await client_manager.get_or_create_client(server_url)
        if not client:
            return f"无法连接到服务器 {server_url}"

        node = client.get_node(node_id)
        value = await asyncio.to_thread(node.get_value)
        return f"服务器 {server_url} - 节点 {node_id} 的值: {value}"

    except Exception as e:
        return f"读取节点失败: {str(e)}"


# 工具：向OPC UA节点写入值
@mcp.tool()
async def write_opcua_node(server_url: str, node_id: str, value: str, ctx: Context) -> str:

    try:
        client = await client_manager.get_or_create_client(server_url)
        if not client:
            return f"无法连接到服务器 {server_url}"

        node = client.get_node(node_id)

        current_value = await asyncio.to_thread(node.get_value)

        if isinstance(current_value, (int, float)):
            await asyncio.to_thread(node.set_value, float(value))
        elif isinstance(current_value, bool):
            bool_value = str(value).lower() in ['true', '1', 'yes', 'on']
            await asyncio.to_thread(node.set_value, bool_value)
        else:
            await asyncio.to_thread(node.set_value, value)

        return f"成功将 {value} 写入服务器 {server_url} 的节点 {node_id}"

    except Exception as e:
        return f"写入节点失败: {str(e)}"


# 工具：读取多个OPC UA节点
@mcp.tool()
async def read_multiple_opcua_nodes(
        server_url: str,
        node_ids: List[str],
        ctx: Context
) -> str:

    try:
        client = await client_manager.get_or_create_client(server_url)
        if not client:
            return f"无法连接到服务器 {server_url}"

        results = {}
        for node_id in node_ids:
            try:
                node = client.get_node(node_id)
                value = await asyncio.to_thread(node.get_value)
                results[node_id] = value
            except Exception as e:
                results[node_id] = f"错误: {str(e)}"

        formatted = f"服务器 {server_url} - 多个节点读取结果:\n\n"
        for node_id, value in results.items():
            formatted += f"• {node_id}: {value}\n"

        return formatted

    except Exception as e:
        return f"读取多个节点失败: {str(e)}"


# 工具：写入多个OPC UA节点
@mcp.tool()
async def write_multiple_opcua_nodes(
        server_url: str,
        nodes_to_write: List[Dict[str, Any]],
        ctx: Context
) -> str:

    try:
        client = await client_manager.get_or_create_client(server_url)
        if not client:
            return f"无法连接到服务器 {server_url}"

        results = []
        for item in nodes_to_write:
            node_id = item['node_id']
            value = item['value']

            try:
                node = client.get_node(node_id)

                # 基于节点当前类型转换值
                current_value = await asyncio.to_thread(node.get_value)
                if isinstance(current_value, (int, float)):
                    converted_value = float(value)
                elif isinstance(current_value, bool):
                    converted_value = str(value).lower() in ['true', '1', 'yes', 'on']
                else:
                    converted_value = str(value)

                await asyncio.to_thread(node.set_value, converted_value)
                results.append({"node_id": node_id, "status": "成功"})

            except Exception as e:
                results.append({"node_id": node_id, "status": f"错误: {str(e)}"})

        formatted = f"服务器 {server_url} - 写入操作结果:\n\n"
        for result in results:
            formatted += f"• {result['node_id']}: {result['status']}\n"

        return formatted

    except Exception as e:
        return f"写入多个节点失败: {str(e)}"

if __name__ == "__main__":

    mcp.run(transport='stdio')