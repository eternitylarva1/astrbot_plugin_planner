"""
LLM 服务模块 - 独立的 LLM 调用接口
不依赖 AstrBot，通过配置文件获取 API 密钥
"""

import aiohttp
import json
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class LLMService:
    """独立的 LLM 调用服务"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化 LLM 服务
        
        Args:
            config: 插件配置字典，包含 llm_api_base, llm_api_key, llm_model
        """
        self.api_base = config.get("llm_api_base", "https://api.openai.com/v1")
        self.api_key = config.get("llm_api_key", "")
        self.model = config.get("llm_model", "gpt-4o-mini")
        self.timeout = 60  # 超时时间（秒）
        
        if not self.api_key:
            logger.warning("LLM API key 未配置，LLM 功能将不可用")
    
    def is_configured(self) -> bool:
        """检查 LLM 是否已配置"""
        return bool(self.api_key and self.api_base)
    
    async def generate(
        self,
        prompt: str,
        system: str = "You are a helpful assistant.",
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> Optional[str]:
        """
        调用 LLM 生成文本
        
        Args:
            prompt: 用户提示词
            system: 系统提示词
            temperature: 温度参数（0-1，越高越随机）
            max_tokens: 最大 token 数
            
        Returns:
            LLM 生成的文本，失败返回 None
        """
        if not self.is_configured():
            logger.error("LLM 未配置，请检查 llm_api_base、llm_api_key、llm_model 配置")
            return None
        
        url = f"{self.api_base.rstrip('/')}/chat/completions"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"LLM API 调用失败: {response.status} - {error_text}")
                        return None
                    
                    data = await response.json()
                    
                    # 解析 OpenAI 格式的响应
                    if "choices" in data and len(data["choices"]) > 0:
                        return data["choices"][0]["message"]["content"]
                    else:
                        logger.error(f"LLM 响应格式错误: {data}")
                        return None
                        
        except aiohttp.ClientError as e:
            logger.error(f"LLM 网络请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"LLM 调用异常: {e}")
            return None
    
    async def breakdown_task(self, task_name: str) -> Optional[List[Dict]]:
        """
        将大任务拆解成小任务
        
        Args:
            task_name: 任务名称
            
        Returns:
            拆解后的子任务列表，每个任务包含 name 和 duration（分钟）
        """
        system_prompt = """你是一个任务拆解专家。将大任务拆解成具体可执行的小任务。

要求：
1. 只输出纯文本列表格式，不要 Markdown 标题
2. 每个子任务一行，格式：- 任务名称 | 时长(数字)
3. 时长用阿拉伯数字表示，单位是分钟
4. 示例格式：
- 确定研究领域 | 30
- 检索文献资料 | 45
- 撰写开题报告 | 60

只输出任务列表，每行一个，不要其他说明文字。"""
        
        prompt = f"拆解任务：{task_name}"
        
        response = await self.generate(prompt, system=system_prompt, temperature=0.5)
        
        if not response:
            return None
        
        # 解析响应，提取任务列表
        tasks = self._parse_breakdown_response(response)
        logger.info(f"Parsed {len(tasks)} tasks from LLM response")
        return tasks
    
    def _parse_breakdown_response(self, response: str) -> List[Dict]:
        """
        解析 LLM 响应，提取任务列表
        
        Args:
            response: LLM 返回的文本
            
        Returns:
            任务字典列表
        """
        tasks = []
        lines = response.strip().split("\n")
        
        for line in lines:
            line = line.strip()
            if not line or not line.startswith("-"):
                continue
            
            # 移除 "- " 前缀
            content = line[1:].strip()
            
            # 尝试提取时长
            duration = 30  # 默认 30 分钟
            name = content
            
            # 查找 " | 数字分钟" 或 " | 数字分钟" 格式
            import re
            match = re.search(r"(.+?)\s*\|\s*(\d+)\s*分钟?", content)
            if match:
                name = match.group(1).strip()
                duration = int(match.group(2))
            else:
                # 尝试匹配纯数字结尾
                match = re.search(r"(.+?)\s*\|\s*(\d+)", content)
                if match:
                    name = match.group(1).strip()
                    duration = int(match.group(2))
            
            if name:
                tasks.append({
                    "name": name,
                    "duration": duration
                })
        
        return tasks


# 全局实例（会在初始化时创建）
_llm_service: Optional[LLMService] = None


def get_llm_service(config: Dict[str, Any] = None) -> Optional[LLMService]:
    """
    获取 LLM 服务实例
    
    Args:
        config: 插件配置，如果为 None 则返回全局实例
        
    Returns:
        LLMService 实例
    """
    global _llm_service
    
    if config is not None:
        _llm_service = LLMService(config)
    
    return _llm_service


def init_llm_service(config: Dict[str, Any]) -> LLMService:
    """
    初始化 LLM 服务
    
    Args:
        config: 插件配置字典
        
    Returns:
        LLMService 实例
    """
    global _llm_service
    _llm_service = LLMService(config)
    return _llm_service
