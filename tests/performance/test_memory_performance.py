"""性能基准测试"""
import pytest
import time
from lighthermes.memory import MemoryManager, MemoryIndex


@pytest.mark.performance
@pytest.mark.slow
class TestMemoryPerformance:
    """测试记忆系统性能"""

    def test_index_add_performance(self, temp_memory_dir):
        """测试索引添加性能"""
        index = MemoryIndex(f"{temp_memory_dir}/index.json")

        start = time.time()
        for i in range(100):
            index.add(f"doc_{i}", f"这是第{i}个测试文档，包含Python和Java的内容")
        elapsed = time.time() - start

        # 100 条记忆应该在 1 秒内完成
        assert elapsed < 1.0, f"添加 100 条记忆耗时 {elapsed:.3f}s，超过 1s"

    def test_index_search_performance(self, temp_memory_dir):
        """测试索引搜索性能"""
        index = MemoryIndex(f"{temp_memory_dir}/index.json")

        # 添加 100 条记忆
        for i in range(100):
            index.add(f"doc_{i}", f"这是第{i}个测试文档，包含Python和Java的内容")

        # 测试搜索性能
        start = time.time()
        for _ in range(100):
            index.search(["python"])
        elapsed = time.time() - start

        # 100 次搜索应该在 0.1 秒内完成
        avg_time = elapsed / 100
        assert avg_time < 0.001, f"平均搜索耗时 {avg_time*1000:.2f}ms，超过 1ms"

    def test_memory_recall_performance(self, temp_memory_dir):
        """测试记忆召回性能"""
        mm = MemoryManager(
            memory_dir=temp_memory_dir,
            use_hybrid_retrieval=False
        )

        # 添加 50 条记忆
        for i in range(50):
            mm.semantic.save(
                f"memory_{i}",
                f"这是第{i}个记忆，关于Python编程的内容",
                {"type": "knowledge"}
            )

        # 测试召回性能
        start = time.time()
        for _ in range(10):
            mm.recall("Python编程")
        elapsed = time.time() - start

        # 10 次召回应该在 1 秒内完成
        avg_time = elapsed / 10
        assert avg_time < 0.1, f"平均召回耗时 {avg_time*1000:.2f}ms，超过 100ms"


@pytest.mark.performance
class TestMemoryScalability:
    """测试记忆系统可扩展性"""

    def test_large_memory_set(self, temp_memory_dir):
        """测试大量记忆场景"""
        mm = MemoryManager(
            memory_dir=temp_memory_dir,
            use_hybrid_retrieval=False
        )

        # 添加 500 条记忆
        start = time.time()
        for i in range(500):
            mm.semantic.save(
                f"memory_{i}",
                f"记忆内容 {i}",
                {"type": "test"}
            )
        add_time = time.time() - start

        # 测试召回
        start = time.time()
        result = mm.recall("记忆")
        recall_time = time.time() - start

        print(f"\n添加 500 条记忆: {add_time:.3f}s")
        print(f"召回耗时: {recall_time*1000:.2f}ms")

        # 召回应该在 200ms 内完成
        assert recall_time < 0.2, f"召回耗时 {recall_time*1000:.2f}ms，超过 200ms"
