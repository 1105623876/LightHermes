"""
LightHermes 完整系统测试
测试所有核心功能模块
"""

import sys
import tempfile
import time
import os

sys.path.insert(0, '.')

def test_memory_system():
    """测试记忆系统（中英文混合检索）"""
    print('1. 测试记忆系统（中英文混合检索）')

    from lighthermes.memory import MemoryManager

    temp_dir = tempfile.mkdtemp()
    mm = MemoryManager(memory_dir=temp_dir, use_hybrid_retrieval=False)

    # 保存测试记忆
    mm.semantic.save('python_basics', 'Python是一种高级编程语言，适合初学者学习，语法简洁优雅', {'type': 'knowledge'})
    mm.semantic.save('java_basics', 'Java是一种面向对象的编程语言，广泛用于企业开发', {'type': 'knowledge'})
    mm.semantic.save('react_basics', 'React是一个用于构建用户界面的JavaScript库', {'type': 'knowledge'})

    # 测试中文查询
    result1 = mm.recall('Python编程')
    status1 = 'PASS' if 'Python' in result1 or 'python' in result1 else 'FAIL'
    print(f'  中文查询 "Python编程": {status1}')

    # 测试英文查询
    result2 = mm.recall('Java')
    status2 = 'PASS' if 'Java' in result2 or 'java' in result2 else 'FAIL'
    print(f'  英文查询 "Java": {status2}')

    # 测试混合查询
    result3 = mm.recall('JavaScript库')
    status3 = 'PASS' if 'React' in result3 or 'react' in result3 else 'FAIL'
    print(f'  混合查询 "JavaScript库": {status3}')

    return all([status1 == 'PASS', status2 == 'PASS', status3 == 'PASS'])


def test_core_imports():
    """测试核心模块导入"""
    print('\n2. 测试核心模块导入')

    results = []

    try:
        from lighthermes import LightHermes
        print('  LightHermes: PASS')
        results.append(True)
    except Exception as e:
        print(f'  LightHermes: FAIL ({e})')
        results.append(False)

    try:
        from lighthermes.memory import MemoryManager
        print('  MemoryManager: PASS')
        results.append(True)
    except Exception as e:
        print(f'  MemoryManager: FAIL ({e})')
        results.append(False)

    try:
        from lighthermes.evolution import EvolutionEngine
        print('  EvolutionEngine: PASS')
        results.append(True)
    except Exception as e:
        print(f'  EvolutionEngine: FAIL ({e})')
        results.append(False)

    try:
        from lighthermes.adapters import get_adapter
        print('  Adapters: PASS')
        results.append(True)
    except Exception as e:
        print(f'  Adapters: FAIL ({e})')
        results.append(False)

    try:
        from lighthermes.compressor import ContextCompressor
        print('  ContextCompressor: PASS')
        results.append(True)
    except Exception as e:
        print(f'  ContextCompressor: FAIL ({e})')
        results.append(False)

    return all(results)


def test_skill_loader():
    """测试技能加载系统"""
    print('\n3. 测试技能加载系统')

    from lighthermes.core import SkillLoader

    skill_dirs = ['skills/core', 'skills/user', 'skills/generated']
    loader = SkillLoader(skill_dirs)

    print(f'  加载的技能数量: {len(loader.skills)}')
    if loader.skills:
        print(f'  技能列表（前3个）:')
        for i, (name, skill) in enumerate(list(loader.skills.items())[:3]):
            desc = skill.get('description', '无描述')[:40]
            print(f'    - {name}: {desc}...')
        return True
    else:
        print('  WARNING: 未找到技能文件')
        return True  # 不算失败，可能没有技能文件


def test_memory_index_performance():
    """测试记忆索引性能"""
    print('\n4. 测试记忆索引性能')

    from lighthermes.memory import MemoryIndex

    temp_dir = tempfile.mkdtemp()
    index_file = f'{temp_dir}/test_index.json'
    index = MemoryIndex(index_file)

    # 添加 100 条记忆
    start = time.time()
    for i in range(100):
        index.add(f'doc_{i}', f'这是第{i}个测试文档，包含Python和Java的内容')
    add_time = time.time() - start

    # 测试搜索性能
    start = time.time()
    for _ in range(100):
        result = index.search(['python'])
    search_time = time.time() - start

    print(f'  添加 100 条记忆耗时: {add_time:.3f}s')
    print(f'  执行 100 次搜索耗时: {search_time:.3f}s')
    print(f'  平均搜索耗时: {search_time/100*1000:.2f}ms')

    # 性能要求：平均搜索 < 10ms
    return (search_time / 100) < 0.01


def test_fixed_memory_files():
    """测试 SOUL.md 和 USER.md 解析"""
    print('\n5. 测试 SOUL.md 和 USER.md 解析')

    from lighthermes.memory import parse_memory_file

    results = []

    soul_path = 'memory/SOUL.md'
    if os.path.exists(soul_path):
        soul = parse_memory_file(soul_path)
        if soul:
            print(f'  SOUL.md 解析: PASS')
            print(f'    内容长度: {len(soul["content"])} 字符')
            results.append(True)
        else:
            print(f'  SOUL.md 解析: FAIL')
            results.append(False)
    else:
        print(f'  SOUL.md: 文件不存在')
        results.append(True)  # 不算失败

    user_path = 'memory/USER.md'
    if os.path.exists(user_path):
        user = parse_memory_file(user_path)
        if user:
            print(f'  USER.md 解析: PASS')
            print(f'    内容长度: {len(user["content"])} 字符')
            results.append(True)
        else:
            print(f'  USER.md 解析: FAIL')
            results.append(False)
    else:
        print(f'  USER.md: 文件不存在')
        results.append(True)  # 不算失败

    return all(results)


def test_tokenization():
    """测试分词功能"""
    print('\n6. 测试分词功能')

    from lighthermes.memory import MemoryIndex

    temp_dir = tempfile.mkdtemp()
    index_file = f'{temp_dir}/test_index.json'
    index = MemoryIndex(index_file)

    test_cases = [
        ('纯中文', '这是一个测试'),
        ('纯英文', 'This is a test'),
        ('中英混合', 'Python是一种编程语言'),
        ('带标点', 'Hello, 世界！'),
        ('带数字', 'Python3.11版本')
    ]

    print('  分词测试:')
    all_passed = True
    for name, text in test_cases:
        tokens = index._tokenize(text)
        print(f'    {name}: {len(tokens)} 个 token')
        if len(tokens) == 0:
            all_passed = False

    return all_passed


def test_memory_stats():
    """测试记忆统计系统"""
    print('\n7. 测试记忆统计系统')

    from lighthermes.memory import MemoryStats

    temp_dir = tempfile.mkdtemp()
    stats_file = f'{temp_dir}/stats.json'
    stats = MemoryStats(stats_file)

    # 记录一些统计
    stats.record_hit('semantic', 3, 0.05)
    stats.record_hit('semantic', 2, 0.03)
    stats.record_hit('episodic', 1, 0.02)

    # 获取命中率
    semantic_rate = stats.get_hit_rate('semantic')
    episodic_rate = stats.get_hit_rate('episodic')

    print(f'  语义记忆命中率: {semantic_rate:.2f}')
    print(f'  情景记忆命中率: {episodic_rate:.2f}')

    all_stats = stats.get_all_stats()
    print(f'  统计层级数: {len(all_stats)}')

    return len(all_stats) > 0


def main():
    print('=== LightHermes 完整系统测试 ===\n')

    results = {}

    try:
        results['记忆系统'] = test_memory_system()
    except Exception as e:
        print(f'  ERROR: {e}')
        results['记忆系统'] = False

    try:
        results['核心导入'] = test_core_imports()
    except Exception as e:
        print(f'  ERROR: {e}')
        results['核心导入'] = False

    try:
        results['技能加载'] = test_skill_loader()
    except Exception as e:
        print(f'  ERROR: {e}')
        results['技能加载'] = False

    try:
        results['索引性能'] = test_memory_index_performance()
    except Exception as e:
        print(f'  ERROR: {e}')
        results['索引性能'] = False

    try:
        results['固定记忆'] = test_fixed_memory_files()
    except Exception as e:
        print(f'  ERROR: {e}')
        results['固定记忆'] = False

    try:
        results['分词功能'] = test_tokenization()
    except Exception as e:
        print(f'  ERROR: {e}')
        results['分词功能'] = False

    try:
        results['记忆统计'] = test_memory_stats()
    except Exception as e:
        print(f'  ERROR: {e}')
        results['记忆统计'] = False

    # 输出测试总结
    print('\n' + '='*50)
    print('测试总结:')
    print('='*50)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        status = 'PASS' if result else 'FAIL'
        print(f'  {name}: {status}')

    print(f'\n通过率: {passed}/{total} ({passed/total*100:.1f}%)')

    if passed == total:
        print('\n所有测试通过！')
        return 0
    else:
        print(f'\n{total - passed} 个测试失败')
        return 1


if __name__ == '__main__':
    sys.exit(main())
