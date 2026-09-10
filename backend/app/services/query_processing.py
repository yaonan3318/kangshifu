"""不依赖大模型的查询规范化、公司词典扩展与拼写纠正。

词典来自配置字符串与数据库（管理员维护），不写死在代码里；同义词/缩写/专有名词
统一按「命中任一词就扩展整组」处理，因此天然支持简称与全称双向映射。
"""

from dataclasses import dataclass
import re


SPACE_PATTERN = re.compile(r"\s+")
CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")


@dataclass(frozen=True)
class ProcessedQuery:
    original: str
    normalized: str
    expanded_terms: list[str]
    retrieval_text: str
    corrections: list[str]


def _edit_distance(left: str, right: str, limit: int = 2) -> int:
    """受限编辑距离；超过 limit 提前返回，避免无谓计算。"""
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


class QueryProcessor:
    def __init__(
        self,
        synonym_config: str = "",
        dictionary: dict[str, list[str]] | None = None,
        spelling_correction: bool = False,
    ):
        self.synonyms = self._parse_synonyms(synonym_config)
        for term, expansions in (dictionary or {}).items():
            merged = list(dict.fromkeys([*self.synonyms.get(term, []), *expansions]))
            self.synonyms[term] = merged
        self.spelling_correction = spelling_correction
        terms: list[str] = []
        for key, values in self.synonyms.items():
            terms.append(key)
            terms.extend(values)
        self.known_terms = list(dict.fromkeys(term for term in terms if term))
        # 拼写纠正只对 ASCII 词生效，且词长至少 3，避免把短词误纠。
        self._correctable_terms = [term for term in self.known_terms if term.isascii() and len(term) >= 3]

    def process(self, query: str) -> ProcessedQuery:
        normalized = SPACE_PATTERN.sub(" ", query.strip()).lower()
        expanded: list[str] = []
        for key, values in self.synonyms.items():
            if key in normalized or any(value in normalized for value in values):
                expanded.extend([key, *values])
        corrections = self._spelling_corrections(normalized)
        expanded.extend(corrections)
        expanded = list(dict.fromkeys(term for term in expanded if term and term not in normalized))
        retrieval_text = " ".join([normalized, *expanded]).strip()
        return ProcessedQuery(query.strip(), normalized, expanded, retrieval_text, corrections)

    def _spelling_corrections(self, normalized: str) -> list[str]:
        if not self.spelling_correction or not self._correctable_terms:
            return []
        corrections: list[str] = []
        for token in normalized.split():
            if len(token) < 3 or not token.isascii() or CJK_PATTERN.search(token):
                continue
            if token in self.synonyms or token in self._correctable_terms:
                continue
            best: str | None = None
            best_distance = 2
            for term in self._correctable_terms:
                distance = _edit_distance(token, term, limit=1)
                if distance < best_distance:
                    best, best_distance = term, distance
                    if distance == 1:
                        break
            if best is not None and best_distance == 1:
                corrections.append(best)
        return corrections

    @staticmethod
    def _parse_synonyms(value: str) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for group in value.split(";"):
            names = [item.strip().lower() for item in group.split("|") if item.strip()]
            if len(names) >= 2:
                result[names[0]] = names[1:]
        return result
