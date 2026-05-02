"""记忆系统单元测试"""
import pytest
from lighthermes.memory import (
    MemoryManager,
    MemoryIndex,
    MemoryStats,
    ShortTermMemory,
    parse_memory_file,
    parse_memory_file_content
)


@pytest.mark.unit
class TestMemoryIndex:
    """测试记忆索引"""

    def test_tokenization_chinese(self, temp_memory_dir):
        """测试中文分词"""
        index = MemoryIndex(f"{temp_memory_dir}/index.json")
        tokens = index._tokenize("这是一个测试")
        assert len(tokens) > 0
        assert "这" in tokens
        assert "是" in tokens

    def test_tokenization_english(self, temp_memory_dir):
        """测试英文分词"""
        index = MemoryIndex(f"{temp_memory_dir}/index.json")
        tokens = index._tokenize("This is a test")
        assert "this" in tokens
        assert "is" in tokens
        assert "test" in tokens

    def test_tokenization_mixed(self, temp_memory_dir):
        """测试中英文混合分词"""
        index = MemoryIndex(f"{temp_memory_dir}/index.json")
        tokens = index._tokenize("Python是一种编程语言")
        assert "python" in tokens
        assert "是" in tokens
        assert "编" in tokens

    def test_add_and_search(self, temp_memory_dir):
        """测试添加和搜索"""
        index = MemoryIndex(f"{temp_memory_dir}/index.json")
        index.add("doc1", "Python是一种编程语言")
        index.add("doc2", "Java是另一种语言")

        # 搜索 Python
        results = index.search(["python"])
        assert "doc1" in results

        # 搜索中文
        results = index.search(["编"])
        assert "doc1" in results


@pytest.mark.unit
class TestMemoryStats:
    """测试记忆统计"""

    def test_record_and_get_hit_rate(self, temp_memory_dir):
        """测试记录和获取命中率"""
        stats = MemoryStats(f"{temp_memory_dir}/stats.json")

        # 记录命中
        stats.record_hit("semantic", 3, 0.05)
        stats.record_hit("semantic", 2, 0.03)

        # 获取命中率
        rate = stats.get_hit_rate("semantic")
        assert rate == 2.5  # (3 + 2) / 2

    def test_get_all_stats(self, temp_memory_dir):
        """测试获取所有统计"""
        stats = MemoryStats(f"{temp_memory_dir}/stats.json")

        stats.record_hit("semantic", 3, 0.05)
        stats.record_hit("episodic", 1, 0.02)

        all_stats = stats.get_all_stats()
        assert "semantic" in all_stats
        assert "episodic" in all_stats


@pytest.mark.unit
class TestShortTermMemory:
    """测试短期记忆"""

    def test_add_and_get_messages(self):
        """测试添加和获取消息"""
        stm = ShortTermMemory(max_turns=5)

        stm.add("user", "Hello")
        stm.add("assistant", "Hi there")

        messages = stm.get_messages()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"

    def test_max_turns_limit(self):
        """测试最大轮数限制"""
        stm = ShortTermMemory(max_turns=2)

        for i in range(5):
            stm.add("user", f"Message {i}")

        messages = stm.get_messages()
        # 最多保留 2 * 2 = 4 条消息
        assert len(messages) <= 4

    def test_clear(self):
        """测试清空"""
        stm = ShortTermMemory()
        stm.add("user", "Hello")
        stm.clear()

        messages = stm.get_messages()
        assert len(messages) == 0


@pytest.mark.unit
class TestMemoryManager:
    """测试记忆管理器"""

    def test_initialization(self, temp_memory_dir):
        """测试初始化"""
        mm = MemoryManager(
            memory_dir=temp_memory_dir,
            use_hybrid_retrieval=False
        )
        assert mm.short_term is not None
        assert mm.working is not None
        assert mm.episodic is not None
        assert mm.semantic is not None

    def test_save_and_recall(self, temp_memory_dir, sample_memory_content):
        """测试保存和召回"""
        mm = MemoryManager(
            memory_dir=temp_memory_dir,
            use_hybrid_retrieval=False
        )

        # 保存记忆
        for name, content in sample_memory_content.items():
            mm.semantic.save(name, content, {"type": "knowledge"})

        # 召回记忆
        result = mm.recall("Python编程")
        assert "Python" in result or "python" in result


@pytest.mark.unit
class TestMemoryFileParsing:
    """测试记忆文件解析"""

    def test_parse_valid_frontmatter(self):
        """测试解析有效的 frontmatter"""
        content = """---
type: test
name: test_memory
---

This is test content"""

        result = parse_memory_file_content(content)
        assert result is not None
        assert result["metadata"]["type"] == "test"
        assert result["content"] == "This is test content"

    def test_parse_invalid_frontmatter(self):
        """测试解析无效的 frontmatter"""
        content = "No frontmatter here"
        result = parse_memory_file_content(content)
        assert result is None

    def test_parse_empty_content(self):
        """测试解析空内容"""
        content = """---
type: test
---

"""
        result = parse_memory_file_content(content)
        assert result is not None
        assert result["content"] == ""
