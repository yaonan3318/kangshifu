"""不依赖大模型的查询规范化与公司同义词扩展。"""

from dataclasses import dataclass
import re


SPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True)
class ProcessedQuery:
    original: str
    normalized: str
    expanded_terms: list[str]
    retrieval_text: str


class QueryProcessor:
    def __init__(self, synonym_config: str = ""):
        self.synonyms = self._parse_synonyms(synonym_config)

    def process(self, query: str) -> ProcessedQuery:
        normalized = SPACE_PATTERN.sub(" ", query.strip()).lower()
        expanded: list[str] = []
        for key, values in self.synonyms.items():
            if key in normalized or any(value in normalized for value in values):
                expanded.extend([key, *values])
        expanded = list(dict.fromkeys(term for term in expanded if term and term not in normalized))
        retrieval_text = " ".join([normalized, *expanded]).strip()
        return ProcessedQuery(query.strip(), normalized, expanded, retrieval_text)

    @staticmethod
    def _parse_synonyms(value: str) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for group in value.split(";"):
            names = [item.strip().lower() for item in group.split("|") if item.strip()]
            if len(names) >= 2:
                result[names[0]] = names[1:]
        return result
