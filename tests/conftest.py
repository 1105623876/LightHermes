"""测试配置和共享 fixtures"""
import pytest
import tempfile
import os
from pathlib import Path


@pytest.fixture
def temp_memory_dir():
    """创建临时记忆目录"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # 清理
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_api_key():
    """提供测试用的 API key"""
    return "test_api_key_12345"


@pytest.fixture
def sample_memory_content():
    """提供测试用的记忆内容"""
    return {
        "python": "Python是一种高级编程语言，适合初学者学习",
        "java": "Java是一种面向对象的编程语言，广泛用于企业开发",
        "react": "React是一个用于构建用户界面的JavaScript库"
    }
