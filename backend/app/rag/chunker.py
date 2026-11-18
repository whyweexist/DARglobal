"""Hierarchy-preserving, tokenizer-aware chunker with bounded overlap."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import re


@dataclass(frozen=True)
class TextChunk:
    heading: str
    text: str
    tokens: int
    checksum: str


class Tokenizer:
    def __init__(self):
        try:
            import tiktoken
            self.encoding = tiktoken.get_encoding("cl100k_base")
        except (ImportError, OSError):
            self.encoding = None

    def tokens(self, text: str) -> list[int] | list[str]:
        if self.encoding:
            return self.encoding.encode(text)
        return re.findall(r"\w+|[^\w\s]", text, re.UNICODE)

    def length(self, text: str) -> int:
        return len(self.tokens(text))

    def trim(self, text: str, max_tokens: int) -> str:
        toks = self.tokens(text)
        if len(toks) <= max_tokens:
            return text
        if self.encoding:
            return self.encoding.decode(toks[:max_tokens])
        return " ".join(toks[:max_tokens])


class StructureAwareChunker:
    def __init__(self, target: int = 400, maximum: int = 600, overlap: int = 60):
        if not (0 <= overlap < target <= maximum):
            raise ValueError("Expected 0 <= overlap < target <= maximum")
        self.target, self.maximum, self.overlap = target, maximum, overlap
        self.tokenizer = Tokenizer()

    def chunk(self, sections: list[tuple[str, str]]) -> list[TextChunk]:
        result: list[TextChunk] = []
        for heading, body in sections:
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n|(?<=[.!?。؟])\s+(?=[A-Z\u0600-\u06ff])", body) if p.strip()]
            segments: list[str] = []
            for part in paragraphs:
                if self.tokenizer.length(part) <= self.maximum - 40:
                    segments.append(part)
                    continue
                # Oversize paragraphs are sliced on token boundaries.
                tokens = self.tokenizer.tokens(part)
                stride = max(1, self.maximum - 40 - self.overlap)
                for start in range(0, len(tokens), stride):
                    fragment = tokens[start:start + self.maximum - 40]
                    if not fragment:
                        continue
                    segments.append(self.tokenizer.encoding.decode(fragment) if self.tokenizer.encoding else " ".join(fragment))
                    if start + self.maximum - 40 >= len(tokens):
                        break
            buffer = ""
            for segment in segments:
                if buffer and self.tokenizer.length(buffer + " " + segment) > self.target:
                    self._append(result, heading, buffer)
                    if self.overlap:
                        toks = self.tokenizer.tokens(buffer)
                        suffix = toks[-self.overlap:]
                        previous = (self.tokenizer.encoding.decode(suffix) if self.tokenizer.encoding else " ".join(suffix))
                        buffer = previous + " " + segment
                    else:
                        buffer = segment
                    if self.tokenizer.length(buffer) > self.maximum:
                        buffer = segment
                else:
                    buffer = f"{buffer} {segment}".strip()
            if buffer:
                self._append(result, heading, buffer)
        return result

    def _append(self, result: list[TextChunk], heading: str, body: str):
        text = f"{heading}\n{body}" if heading else body
        text = self.tokenizer.trim(text.strip(), self.maximum)
        if self.tokenizer.length(text) < 12:
            return
        digest = hashlib.sha256(text.encode()).hexdigest()
        if not result or result[-1].checksum != digest:
            result.append(TextChunk(heading[:650], text, self.tokenizer.length(text), digest))
