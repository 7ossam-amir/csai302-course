"""A basic Retrieval-Augmented Generation (RAG) system over this course's own lab guides.

Pipeline:
  1. Load:     every labs/labNN/README.md, split by headings, long sections cut into ~120-word
               overlapping chunks (code blocks removed).
  2. Embed:    a hashed TF-IDF embedding of words and word pairs into a 1,024-d vector. Real
               systems use a neural embedding model; this one needs no download and is
               deterministic, so retrieval results are repeatable.
  3. Index:    the HNSW index from vector_search.py (or exact search, for comparison).
  4. Retrieve: the k chunks closest to the question.
  5. Generate: build the grounded prompt a language model would receive, and produce an
               extractive answer: the best-matching sentences of the retrieved chunks, each
               with its source. Every sentence of the answer is copied from the course notes,
               so the answer cannot contain facts that the retrieved context does not.

    python labs/lab09/rag.py "Why must the log be flushed before a dirty page is written?"
    python labs/lab09/rag.py --show-prompt "What is write skew?"
    python labs/lab09/rag.py --eval
"""

from __future__ import annotations

import argparse
import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from vector_search import HNSWIndex, exact_knn

REPO_ROOT = Path(__file__).resolve().parents[2]
STOPWORDS = set("""a an and are as at be by can do does for from has have how if in into is it its
of on or so than that the their then there these this to was what when where which who why will
with would you your not no only also each one two more most may must should could this those
""".split())


@dataclass(frozen=True)
class Chunk:
    id: int
    source: str
    heading: str
    text: str


# --------------------------------------------------------------------- load
def clean_line(line: str, table_header: list[str] | None) -> str:
    """Markdown to plain sentences: table rows become 'cell: cell; cell.', list markers go."""
    line = line.replace("`", "").replace("**", "").strip()
    if line.startswith("|"):
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            return ""  # the |---|---| separator row
        if table_header is None:
            return ""  # header row: its names are added to the data rows instead
        return "; ".join(f"{h}: {c}" if h else c for h, c in zip(table_header, cells) if c) + "."
    return re.sub(r"^(\d+\.|[-*])\s+", "", line)


def split_markdown(text: str, source: str, max_words: int = 120, overlap: int = 30) -> list[tuple[str, str, str]]:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)  # code blocks are poor retrieval text
    pieces, heading, buffer, header = [], source, [], None
    for line in text.splitlines() + ["# end"]:
        if line.strip().startswith("|"):
            cleaned = clean_line(line, header)
            if header is None:
                header = [c.strip() for c in line.strip().strip("|").split("|")]
            buffer.append(cleaned)
            continue
        header = None
        if line.startswith("#"):
            words = " ".join(buffer).split()
            step = max_words - overlap
            for start in range(0, max(len(words) - overlap, 1), step):
                window = words[start:start + max_words]
                if len(window) >= 12:
                    pieces.append((source, heading, " ".join(window)))
            heading, buffer = line.lstrip("# ").strip(), []
        else:
            buffer.append(clean_line(line, None))
    return pieces


def load_course_chunks(root: Path = REPO_ROOT) -> list[Chunk]:
    pieces = []
    for path in sorted(root.glob("labs/lab*/README.md")):
        pieces += split_markdown(path.read_text(encoding="utf-8"), path.parent.name)
    return [Chunk(i, *piece) for i, piece in enumerate(pieces)]


# -------------------------------------------------------------------- embed
def tokenize(text: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS and len(w) > 1]
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]


class HashingEmbedder:
    """Hashed TF-IDF: each known word or word pair adds (1 + log tf) * idf to one of `dim` slots."""

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim
        self.idf = np.ones(dim, dtype=np.float32)
        self.vocabulary: set[str] | None = None

    def _slots(self, text: str) -> Counter:
        tokens = tokenize(text)
        if self.vocabulary is not None:  # words never seen in the corpus carry no evidence
            tokens = [t for t in tokens if t in self.vocabulary]
        return Counter(int.from_bytes(hashlib.blake2b(t.encode(), digest_size=4).digest(), "big") % self.dim
                       for t in tokens)

    def fit(self, texts: list[str]) -> "HashingEmbedder":
        self.vocabulary = {t for text in texts for t in tokenize(text)}
        df = np.zeros(self.dim)
        for text in texts:
            for slot in self._slots(text):
                df[slot] += 1
        self.idf = np.log((1 + len(texts)) / (1 + df)).astype(np.float32) + 1.0
        return self

    def embed(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float32)
        for slot, count in self._slots(text).items():
            vector[slot] += (1 + math.log(count)) * self.idf[slot]
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector


# ---------------------------------------------------------------- the system
@dataclass
class Answer:
    question: str
    text: str
    citations: list[str]
    retrieved: list[tuple[Chunk, float]]
    grounded: bool


class RAG:
    def __init__(self, chunks: list[Chunk], *, index: str = "hnsw", dim: int = 1024, min_score: float = 0.12) -> None:
        if not chunks:
            raise ValueError("the corpus is empty")
        self.chunks = chunks
        self.embedder = HashingEmbedder(dim).fit([c.heading + " " + c.text for c in chunks])
        self.vectors = np.stack([self.embedder.embed(c.heading + " " + c.text) for c in chunks])
        self.index_kind = index
        self.min_score = min_score
        if index == "hnsw":
            self.index = HNSWIndex(dim, M=12, ef_construction=100, seed=0)
            for vector in self.vectors:
                self.index.add(vector if vector.any() else np.ones(dim, dtype=np.float32))

    def retrieve(self, question: str, k: int = 4) -> list[tuple[Chunk, float]]:
        q = self.embedder.embed(question)
        if not q.any():
            return []
        if self.index_kind == "hnsw":
            ids = self.index.search(q, k, ef=max(50, 4 * k))
        else:
            ids = exact_knn(self.vectors, q, k)
        return [(self.chunks[i], float(self.vectors[i] @ q)) for i in ids]

    @staticmethod
    def build_prompt(question: str, retrieved: list[tuple[Chunk, float]]) -> str:
        context = "\n\n".join(f"[{i + 1}] ({c.source} / {c.heading})\n{c.text}" for i, (c, _) in enumerate(retrieved))
        return ("You are a teaching assistant for CSAI 302. Answer the question using ONLY the numbered\n"
                "context passages. Cite passages like [2]. If the context does not contain the answer,\n"
                "say that the course notes do not cover it.\n\n"
                f"Context:\n{context}\n\nQuestion: {question}\nAnswer:")

    def answer(self, question: str, k: int = 4, sentences: int = 3) -> Answer:
        retrieved = self.retrieve(question, k)
        if not retrieved or retrieved[0][1] < self.min_score:
            return Answer(question, "The course notes do not cover this question.", [], retrieved, False)
        q = self.embedder.embed(question)
        candidates = []
        for rank, (chunk, _) in enumerate(retrieved):
            for sentence in re.split(r"(?<=[.!?])\s+", chunk.text):
                if len(sentence.split()) >= 8:  # skip fragments of tables and lists
                    score = float(self.embedder.embed(sentence) @ q) - 0.02 * rank
                    candidates.append((score, rank, sentence.strip()))
        best = sorted(candidates, reverse=True)[:sentences]
        best.sort(key=lambda item: item[1])
        text = " ".join(f"{s} [{rank + 1}]" for _, rank, s in best)
        citations = sorted({f"[{rank + 1}] {retrieved[rank][0].source} / {retrieved[rank][0].heading}"
                            for _, rank, _ in best})
        return Answer(question, text, citations, retrieved, True)


EVAL = [  # question -> lab whose guide should be retrieved
    ("Which page replacement policies did the buffer pool benchmark compare?", "lab02"),
    ("Why is a column store faster than a row store for some queries?", "lab02"),
    ("How does pg_hba.conf reject connections that are not encrypted with TLS?", "lab03"),
    ("Where are large files kept when PostgreSQL stores only their metadata?", "lab03"),
    ("How does an LSM tree handle writes compared with a B+ tree?", "lab04"),
    ("When is an R-tree faster than a linear scan?", "lab04"),
    ("How do bound parameters keep ORM queries safe from SQL injection?", "lab05"),
    ("How does the optimizer use row estimates to choose a plan?", "lab06"),
    ("Why does first-committer-wins still allow write skew?", "lab07"),
    ("What does a cycle in the wait-for graph mean?", "lab07"),
    ("What does a compensation log record do during undo?", "lab08"),
    ("Why must the log be flushed before a dirty page is written to disk?", "lab08"),
]


def evaluate(rag_exact: RAG, rag_hnsw: RAG, k: int = 4) -> None:
    print(f"Retrieval quality on {len(EVAL)} course questions (hit = a chunk from the right lab in the top {k})")
    print(f"  {'question':<74}{'expected':>9}{'exact':>7}{'hnsw':>6}")
    hits = {"exact": 0, "hnsw": 0}
    for question, lab in EVAL:
        row = []
        for name, rag in (("exact", rag_exact), ("hnsw", rag_hnsw)):
            hit = any(c.source == lab for c, _ in rag.retrieve(question, k))
            hits[name] += hit
            row.append("yes" if hit else "NO")
        print(f"  {question[:72]:<74}{lab:>9}{row[0]:>7}{row[1]:>6}")
    print(f"  hit@{k}: exact {hits['exact']}/{len(EVAL)}, HNSW {hits['hnsw']}/{len(EVAL)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question", nargs="?", default="Why must the log be flushed before a dirty page is written?")
    parser.add_argument("-k", type=int, default=4)
    parser.add_argument("--show-prompt", action="store_true", help="print the prompt a language model would get")
    parser.add_argument("--exact", action="store_true", help="retrieve with exact search instead of HNSW")
    parser.add_argument("--eval", action="store_true", help="measure retrieval on the built-in question set")
    args = parser.parse_args()

    chunks = load_course_chunks()
    if args.eval:
        evaluate(RAG(chunks, index="exact"), RAG(chunks, index="hnsw"), args.k)
        return
    rag = RAG(chunks, index="exact" if args.exact else "hnsw")
    print(f"Corpus: {len(chunks)} chunks from {len({c.source for c in chunks})} lab guides; index: {rag.index_kind}\n")
    result = rag.answer(args.question, args.k)
    print(f"Question: {result.question}\n\nRetrieved:")
    for i, (chunk, score) in enumerate(result.retrieved, start=1):
        print(f"  [{i}] {score:.3f}  {chunk.source} / {chunk.heading}")
    print(f"\nAnswer: {result.text}")
    for citation in result.citations:
        print(f"  {citation}")
    if args.show_prompt:
        print("\n----- prompt for a language model -----")
        print(rag.build_prompt(result.question, result.retrieved))


if __name__ == "__main__":
    main()
