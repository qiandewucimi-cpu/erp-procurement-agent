from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Chunk:
    source: str
    section: str
    text: str


def _tokens(text: str) -> set[str]:
    """中英文混合的轻量检索分词，离线也可稳定运行。"""
    normalized = re.sub(r"\s+", "", text.lower())
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    bigrams = {chinese[i : i + 2] for i in range(max(0, len(chinese) - 1))}
    words = set(re.findall(r"[a-z0-9_\-]+", normalized))
    return bigrams | words


class KnowledgeBase:
    """把 Markdown 按标题切块，并返回可展示来源的检索结果。"""

    def __init__(self, knowledge_dir: Path):
        self.chunks: list[Chunk] = []
        for path in sorted(knowledge_dir.glob("*.md")):
            self.chunks.extend(self._load_markdown(path))

    @staticmethod
    def _load_markdown(path: Path) -> list[Chunk]:
        section = "正文"
        buffer: list[str] = []
        chunks: list[Chunk] = []

        def flush() -> None:
            if buffer:
                text = "\n".join(buffer).strip()
                if text:
                    chunks.append(Chunk(path.name, section, text))
                buffer.clear()

        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                flush()
                section = line.lstrip("#").strip()
            elif line.strip():
                buffer.append(line.strip())
        flush()
        return chunks

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        q = _tokens(query)
        scored: list[tuple[float, Chunk]] = []
        for chunk in self.chunks:
            c = _tokens(f"{chunk.section}{chunk.text}")
            overlap = len(q & c)
            score = overlap / max(1, len(q))
            for keyword in ("采购", "po", "bom", "包装费", "确认", "审计"):
                if keyword in query.lower() and keyword in f"{chunk.section}{chunk.text}".lower():
                    score += 0.12
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "source": chunk.source,
                "section": chunk.section,
                "excerpt": chunk.text[:180],
                "score": round(score, 3),
            }
            for score, chunk in scored[:top_k]
        ]

