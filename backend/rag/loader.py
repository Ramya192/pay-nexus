"""
Document ingestion pipeline — loads the Indian tax source files in
rag_documents/ and splits them into embedding-ready chunks.

See PROJECT_CONTEXT.md §5 for the document list this is meant to index
(IT Act sections, Budget highlights, EPFO circulars, state Professional Tax
slabs, HRA rules, Form 16 structure, TDS Section 192 guide) and §11 for
where this fits (backend/rag/loader.py).
"""

from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import config

RAG_DOCUMENTS_DIR = Path(__file__).resolve().parents[2] / "rag_documents"

_LOADERS = {
    ".pdf": PyPDFLoader,
    ".txt": lambda p: TextLoader(p, encoding="utf-8"),
    ".md": lambda p: TextLoader(p, encoding="utf-8"),
}


def load_documents(source_dir: Path = RAG_DOCUMENTS_DIR) -> list[Document]:
    """Load every .pdf/.txt/.md file in source_dir into LangChain Documents.

    Each Document keeps its source path in metadata, so retrieved chunks can
    be traced back to the originating tax document (useful for the
    Regulatory Agent to cite what it's drawing from).
    """
    if not source_dir.exists():
        raise FileNotFoundError(
            f"{source_dir} does not exist — see rag_documents/README.md for "
            "the list of source files to add before running build_index.py"
        )

    docs: list[Document] = []
    for path in sorted(source_dir.glob("**/*")):
        if path.name.lower() == "readme.md":
            continue  # this folder's own instructions file, not a source document
        loader_cls = _LOADERS.get(path.suffix.lower())
        if loader_cls is None:
            continue  # anything else non-source (.gitkeep, etc.)
        for doc in loader_cls(str(path)).load():
            doc.metadata["source"] = path.name
            docs.append(doc)

    if not docs:
        raise ValueError(
            f"No .pdf/.txt/.md files found in {source_dir} — nothing to index. "
            "See rag_documents/README.md."
        )
    return docs


def split_documents(docs: list[Document]) -> list[Document]:
    """Chunk documents per config.RAG_CHUNK_SIZE / RAG_CHUNK_OVERLAP."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.RAG_CHUNK_SIZE,
        chunk_overlap=config.RAG_CHUNK_OVERLAP,
    )
    return splitter.split_documents(docs)
