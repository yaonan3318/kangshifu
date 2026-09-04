"""中英文关键词规范化，为 PostgreSQL simple 全文检索生成词元。"""

import re

import jieba

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+#/-]*|[\u3400-\u9fff]+")


def keyword_text(value: str) -> str:
    """中文使用 jieba 分词，英文转小写去重，返回空格分隔的 PostgreSQL 词元。"""
    tokens: list[str] = []
    seen: set[str] = set()
    for match in TOKEN_PATTERN.findall(value):
        candidates = jieba.cut(match, cut_all=False) if re.search(r"[\u3400-\u9fff]", match) else [match.lower()]
        for candidate in candidates:
            token = candidate.strip().lower()
            if token and token not in seen:
                seen.add(token)
                tokens.append(token)
    return " ".join(tokens)
