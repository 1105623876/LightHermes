"""
LightHermes 上下文压缩系统

实现对话历史的智能压缩，防止 token 溢出
"""

from typing import List, Dict, Any, Optional
import json


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数量（参考 hermes-agent）"""
    return len(text) // 4


class ContextCompressor:
    """上下文压缩器 - 管理对话历史的 token 预算"""

    def __init__(
        self,
        llm_adapter,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        初始化压缩器

        Args:
            llm_adapter: LLM 适配器，用于生成摘要
            config: 压缩配置
        """
        self.llm = llm_adapter
        self.config = config or {}

        # 配置参数
        self.trigger_threshold = self.config.get("trigger_threshold", 0.75)
        self.summary_model = self.config.get("summary_model", "gpt-4o-mini")
        self.protect_first_n = self.config.get("protect_first_n", 3)
        self.protect_recent_tokens = self.config.get("protect_recent_tokens", 20000)
        self.summary_min_tokens = self.config.get("summary_min_tokens", 2000)
        self.summary_max_tokens = self.config.get("summary_max_tokens", 12000)
        self.summary_ratio = self.config.get("summary_ratio", 0.20)

        # 统计信息
        self.compression_count = 0
        self.tokens_saved = 0

    def should_compress(
        self,
        messages: List[Dict[str, Any]],
        context_window: int
    ) -> bool:
        """
        判断是否需要压缩

        Args:
            messages: 消息列表
            context_window: 上下文窗口大小

        Returns:
            是否需要压缩
        """
        total_tokens = sum(estimate_tokens(str(msg)) for msg in messages)
        threshold = self.trigger_threshold * context_window
        return total_tokens > threshold

    def compress(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        压缩消息列表

        Args:
            messages: 原始消息列表

        Returns:
            压缩后的消息列表
        """
        if len(messages) <= self.protect_first_n + 1:
            return messages

        # 1. 工具输出预剪枝
        pruned = self._prune_tool_outputs(messages)

        # 2. 分离头部、中间、尾部
        head = pruned[:self.protect_first_n]
        tail = self._get_recent_messages(
            pruned[self.protect_first_n:],
            self.protect_recent_tokens
        )
        middle_start = self.protect_first_n
        middle_end = len(pruned) - len(tail)

        if middle_end <= middle_start:
            return pruned

        middle = pruned[middle_start:middle_end]

        # 3. 总结中间部分
        if middle:
            original_tokens = sum(estimate_tokens(str(msg)) for msg in middle)
            summary = self._summarize(middle)
            summary_tokens = estimate_tokens(str(summary))

            self.compression_count += 1
            self.tokens_saved += (original_tokens - summary_tokens)

            return head + [summary] + tail

        return pruned

    def _prune_tool_outputs(
        self,
        messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        剪枝工具输出，保留工具调用信息但删除详细输出

        Args:
            messages: 原始消息列表

        Returns:
            剪枝后的消息列表
        """
        result = []
        for msg in messages:
            if msg.get("role") == "tool":
                tool_name = msg.get("name", "unknown")
                result.append({
                    "role": "tool",
                    "name": tool_name,
                    "content": f"[Tool output pruned: {tool_name}]"
                })
            else:
                result.append(msg)
        return result

    def _get_recent_messages(
        self,
        messages: List[Dict[str, Any]],
        token_budget: int
    ) -> List[Dict[str, Any]]:
        """
        获取最近的消息（在 token 预算内）

        Args:
            messages: 消息列表
            token_budget: token 预算

        Returns:
            最近的消息列表
        """
        result = []
        tokens = 0

        for msg in reversed(messages):
            msg_tokens = estimate_tokens(str(msg))
            if tokens + msg_tokens > token_budget:
                break
            result.insert(0, msg)
            tokens += msg_tokens

        return result

    def _summarize(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        总结消息列表

        Args:
            messages: 要总结的消息列表

        Returns:
            包含摘要的消息
        """
        # 构建对话文本
        conversation = "\n".join([
            f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
            for msg in messages
        ])

        # 计算摘要预算
        compressed_tokens = estimate_tokens(conversation)
        summary_budget = min(
            self.summary_max_tokens,
            max(
                self.summary_min_tokens,
                int(compressed_tokens * self.summary_ratio)
            )
        )

        # 生成摘要
        summary_prompt = f"""[CONTEXT COMPACTION — REFERENCE ONLY]

请总结以下对话内容，保留关键信息：

{conversation}

总结要求：
1. 保留已解决的问题和解决方案
2. 保留待处理的问题和讨论点
3. 保留重要的决策和原因
4. 使用简洁的语言，避免冗余
5. 控制在约 {summary_budget} tokens 以内

总结："""

        try:
            # 使用摘要模型生成摘要
            summary_messages = [{"role": "user", "content": summary_prompt}]
            response = self.llm.create(
                messages=summary_messages,
                model=self.summary_model,
                stream=False
            )

            # 提取摘要内容
            if hasattr(response, 'choices'):
                summary_content = response.choices[0].message.content
            else:
                summary_content = str(response)

            return {
                "role": "assistant",
                "content": f"[CONTEXT COMPACTION — REFERENCE ONLY]\n\n{summary_content}"
            }

        except Exception as e:
            # 如果摘要失败，返回简单的占位符
            return {
                "role": "assistant",
                "content": f"[CONTEXT COMPACTION — REFERENCE ONLY]\n\n压缩了 {len(messages)} 条消息（摘要生成失败: {e}）"
            }

    def get_stats(self) -> Dict[str, Any]:
        """
        获取压缩统计信息

        Returns:
            统计信息字典
        """
        return {
            "compression_count": self.compression_count,
            "tokens_saved": self.tokens_saved,
            "avg_tokens_saved": (
                self.tokens_saved // self.compression_count
                if self.compression_count > 0
                else 0
            )
        }
