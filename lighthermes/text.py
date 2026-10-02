"""Shared lexical tokenization; independent of legacy retrieval engines."""
from typing import List


def tokenize_text(text: str) -> List[str]:
    """轻量分词：支持中英文混合。中文按单字、英文/数字按词。

    产品存储和冻结实验共享同一分词规则。
    中文字符（CJK 统一汉字区 \u4e00-\u9fff）按单字切分，英文/数字按连续
    alnum 词切分，空白与标点作为分隔符。
    """
    text = (text or "").lower()
    tokens: List[str] = []
    current_token = ""

    for char in text:
        if '一' <= char <= '鿿':
            if current_token:
                tokens.append(current_token)
                current_token = ""
            tokens.append(char)
        elif char.isalnum():
            current_token += char
        else:
            if current_token:
                tokens.append(current_token)
                current_token = ""

    if current_token:
        tokens.append(current_token)

    return [token for token in tokens if token]
