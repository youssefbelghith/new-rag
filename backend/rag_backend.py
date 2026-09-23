import os
import re
import tempfile
import time
import chromadb
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional, Tuple
from functools import lru_cache
from uuid import uuid4

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_community.vectorstores import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_ollama import ChatOllama
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings

os.environ["CHROMA_TELEMETRY"] = "False"

MODEL_NAME = "llama3"
PERSIST_DIR = "./chroma_db"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150

LANGUAGE_POLICY = """
Response language policy (highest priority):
1. If the user explicitly requests a response language in the question, follow that request.
2. Otherwise, identify the primary language of the user's question and respond entirely in that language.
3. The language of the document or retrieved context must never determine the response language.
Read and extract facts from the document in its original language when necessary, then translate and explain those facts in the required response language.
Do not mention this policy unless the user asks about it.
"""

FACTUAL_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a precise assistant. Answer using only the supplied document context.
{language_policy}
If the answer is not explicitly present in the document, say so clearly in the required response language.
The user's preferred answer style is: {answer_style}."""),
    ("human", """Document context:
{context}

User question:
{question}

Answer:"""),
])

SUMMARY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a helpful assistant specialized in summarizing and extracting conclusions from documents.
{language_policy}
Use all supplied excerpts to produce a concise, coherent summary or answer.
The user's preferred answer style is: {answer_style}."""),
    ("human", """Document context:
{context}

User question:
{question}

Answer:"""),
])

GENERAL_CHAT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a helpful conversational assistant.
{language_policy}
Respond using the user's preferred answer style: {answer_style}."""),
    ("human", """User question:
{question}

Answer:"""),
])

def get_closest_sources(answer: str, vectorstore, embeddings, k: int = 3):
    """Return unique source metadata (file, page) for the top‑k chunks most similar to the generated answer."""
    answer_embedding = embeddings.embed_query(answer)
    docs = vectorstore.similarity_search_by_vector(answer_embedding, k=k)

    sources = []
    seen_files = set()
    for d in docs:
        fname = d.metadata.get("source", "Unknown")
        page = d.metadata.get("page", 0) + 1
        if fname not in seen_files:
            sources.append({"fichier": fname, "page": page})
            seen_files.add(fname)
    return sources

def _is_summary_query(question: str) -> bool:
    keywords = ["résume", "resume", "résumé", "summarize", "summary",
                "conclusion", "conclus", "synthèse", "synthèse",
                "global", "récapitulatif", "overview", "points clés", "conclure",
                "resumes", "résumes"]
    return any(kw in question.lower() for kw in keywords)

# ========== CHUNKING & VECTORSTORE ==========
def _load_file_documents(file_data: Tuple[str, bytes, str]):
    """Extract page documents and file-level metadata for one uploaded file."""
    name, content, document_id = file_data
    extension = name.rsplit(".", 1)[-1].lower()
    if extension not in ["pdf", "md", "markdown"]:
        return document_id, name, []

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{extension}")
    try:
        tmp.write(content)
        tmp.close()
        if extension == "pdf":
            documents = PyPDFLoader(tmp.name).load()
        else:
            documents = [Document(
                page_content=content.decode("utf-8-sig", errors="replace"),
                metadata={"page": 0},
            )]
    finally:
        try:
            tmp.close()
        finally:
            os.unlink(tmp.name)

    return document_id, name, documents


def _chunk_documents(document_id: str, file_name: str, documents: List[Document]):
    """Split pages and apply the canonical metadata schema to every chunk."""
    chunks = []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        add_start_index=True,
    )
    for page_document in documents:
        chunks.extend(splitter.split_documents([page_document]))

    tagged_chunks = []
    for chunk_index, chunk in enumerate(chunks):
        page_number = int(chunk.metadata.get("page", 0)) + 1
        creation_date = (
            chunk.metadata.get("creation_date")
            or chunk.metadata.get("creationDate")
            or chunk.metadata.get("creationdate")
            or ""
        )
        chunk.metadata.update({
            "document_id": document_id,
            "file_name": file_name,
            "page_number": page_number,
            "chunk_id": f"{document_id}:{chunk_index}",
            "chunk_index": chunk_index,
            "creation_date": creation_date,
            "source": file_name,
            "page": page_number - 1,
        })
        tagged_chunks.append(chunk)
    return tagged_chunks


def _parse_and_chunk_files(file_bytes_list: List[Tuple[str, bytes]]):
    """Parse files concurrently, then return tagged chunks and document metadata."""
    file_data = [(name, content, str(uuid4())) for name, content in file_bytes_list]
    with ThreadPoolExecutor(max_workers=min(4, len(file_data))) as executor:
        extracted_files = list(executor.map(_load_file_documents, file_data))

    all_chunks = []
    document_records = []
    for document_id, file_name, documents in extracted_files:
        chunks = _chunk_documents(document_id, file_name, documents)
        all_chunks.extend(chunks)
        document_records.append({
            "document_id": document_id,
            "file_name": file_name,
            "creation_date": next((
                chunk.metadata["creation_date"] for chunk in chunks
                if chunk.metadata["creation_date"]
            ), ""),
            "chunk_count": len(chunks),
        })
    return all_chunks, document_records


def build_vectorstore_from_files(file_bytes_list: List[Tuple[str, bytes]]):
    """Build a vectorstore from multiple files with tagged, filterable chunks."""
    if not file_bytes_list:
        raise ValueError("No files given.")

    tous_les_chunks, document_records = _parse_and_chunk_files(file_bytes_list)

    if not tous_les_chunks:
        raise ValueError("No chunks could be extracted.")

    chroma_client = chromadb.PersistentClient(path=PERSIST_DIR)
    unique_collection_name = f"rag_collection_{int(time.time())}"

    vectordb = Chroma.from_documents(
        documents=tous_les_chunks,
        embedding=get_embeddings(),
        client=chroma_client,
        collection_name=unique_collection_name
    )

    try:
        setattr(vectordb, "_n_chunks", len(tous_les_chunks))
        setattr(vectordb, "_documents", document_records)
    except Exception:
        pass

    return vectordb

def add_single_file_to_vectorstore(uploaded_file, vectordb, document_id=None):
    """Add one uploaded file with the same metadata contract as batch ingestion."""
    name = uploaded_file.name
    content = uploaded_file.read()
    document_id = document_id or str(uuid4())
    _, _, documents = _load_file_documents((name, content, document_id))
    chunks = _chunk_documents(document_id, name, documents)
    if not chunks:
        return vectordb

    vectordb.add_documents(documents=chunks)
    n_actuel = getattr(vectordb, "_n_chunks", 0)
    setattr(vectordb, "_n_chunks", n_actuel + len(chunks))
    documents = getattr(vectordb, "_documents", [])
    documents.append({
        "document_id": document_id,
        "file_name": name,
        "creation_date": next((
            chunk.metadata["creation_date"] for chunk in chunks
            if chunk.metadata["creation_date"]
        ), ""),
        "chunk_count": len(chunks),
    })
    setattr(vectordb, "_documents", documents)

    return vectordb


def add_files_to_vectorstore(file_bytes_list: List[Tuple[str, bytes]], vectordb):
    """Parse and add several files in one concurrent ingestion batch."""
    chunks, document_records = _parse_and_chunk_files(file_bytes_list)
    if not chunks:
        return vectordb, document_records

    vectordb.add_documents(documents=chunks)
    setattr(vectordb, "_n_chunks", getattr(vectordb, "_n_chunks", 0) + len(chunks))
    documents = getattr(vectordb, "_documents", [])
    documents.extend(document_records)
    setattr(vectordb, "_documents", documents)
    return vectordb, document_records

# ========== LLM & EMBEDDINGS ==========
@lru_cache(maxsize=1)
def get_llm():
    """Cache the LLM instance."""
    return ChatOllama(model=MODEL_NAME, temperature=0.2, client_kwargs={"timeout": 120.0})

@lru_cache(maxsize=1)
def get_embeddings():
    """Cache the embeddings model."""
    return HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

def answer_general_question(question: str, answer_style: str = "short and crisp") -> str:
    """Answer a question without document context."""
    prompt = GENERAL_CHAT_PROMPT.format(
        question=question,
        answer_style=answer_style,
        language_policy=LANGUAGE_POLICY,
    )
    return get_llm().invoke(prompt).content

# ========== RAG CHAIN ==========
def _build_metadata_filter(document_ids=None, filter_dict=None):
    """Combine caller filters with an optional document-ID restriction."""
    filters = []
    if filter_dict:
        filters.append(filter_dict)
    if document_ids:
        filters.append({"document_id": {"$in": list(document_ids)}})
    if len(filters) == 1:
        return filters[0]
    if filters:
        return {"$and": filters}
    return None


def _build_retriever(vectordb, k: int = None, filter_dict: dict = None, document_ids=None):
    total_chunks = getattr(vectordb, "_n_chunks", 10)

    if k is None:
        if total_chunks > 500:
            chosen_k = 12
        elif total_chunks > 100:
            chosen_k = 7
        else:
            chosen_k = 4
    else:
        chosen_k = k

    search_kwargs = {
        "k": chosen_k,
        "fetch_k": chosen_k * 4,
        "lambda_mult": 0.15,
    }
    metadata_filter = _build_metadata_filter(document_ids, filter_dict)
    if metadata_filter:
        search_kwargs["filter"] = metadata_filter

    return vectordb.as_retriever(
        search_type="mmr",
        search_kwargs=search_kwargs,
    ), chosen_k


def build_query_retriever(vectordb, k: int = None, filter_dict: dict = None, document_ids=None):
    """Build a retriever for all active documents or selected document IDs."""
    retriever, _ = _build_retriever(
        vectordb,
        k=k,
        filter_dict=filter_dict,
        document_ids=document_ids,
    )
    return retriever

def build_context_from_docs(docs):
    if not docs:
        return "No relevant context found in the document."
    return "\n\n-----\n\n".join(d.page_content for d in docs)

def build_sources_from_docs(docs):
    sources = []
    seen_documents = set()
    for d in docs:
        nom_fichier = d.metadata.get("source", "Unknown")
        document_key = d.metadata.get("document_id") or nom_fichier
        if document_key in seen_documents:
            continue
        seen_documents.add(document_key)
        sources.append({
            "fichier": nom_fichier,
            "page": d.metadata.get("page_number", d.metadata.get("page", 0) + 1),
            "document_id": d.metadata.get("document_id"),
            "chunk_id": d.metadata.get("chunk_id"),
            "score": d.metadata.get("relevance_score"),
        })
    return sources


def _document_key(document):
    metadata = document.metadata
    return metadata.get("chunk_id") or (
        metadata.get("document_id") or metadata.get("source", "Unknown"),
        metadata.get("page_number", metadata.get("page", 0)),
        document.page_content,
    )


def _answer_uses_chunk(answer: str, chunk_text: str) -> bool:
    """Conservative fallback for chunks used by the answer despite a low score."""
    stop_words = {
        "about", "after", "also", "avec", "dans", "from", "have", "into",
        "more", "that", "than", "their", "this", "what", "which", "with",
        "your", "pour", "plus", "sont", "une", "vous", "les", "des", "est",
    }
    answer_terms = {
        term for term in re.findall(r"[\wÀ-ÿ]{4,}", answer.lower())
        if term not in stop_words
    }
    chunk_terms = set(re.findall(r"[\wÀ-ÿ]{4,}", chunk_text.lower()))
    return len(answer_terms & chunk_terms) >= 2


def build_ui_sources(
    question: str,
    answer: str,
    retrieved_docs,
    vectorstore,
    filter_dict: dict = None,
    document_ids=None,
    relevance_threshold: float = 0.65,
):
    """Clean citations after generation without changing the LLM context."""
    if not retrieved_docs:
        return []

    metadata_filter = _build_metadata_filter(document_ids, filter_dict)
    scored_docs = vectorstore.similarity_search_with_relevance_scores(
        question,
        k=max(20, len(retrieved_docs) * 4),
        filter=metadata_filter,
    )
    score_by_chunk = {
        _document_key(document): float(score)
        for document, score in scored_docs
    }

    cleaned_docs = []
    for document in retrieved_docs:
        score = score_by_chunk.get(_document_key(document))
        if score is not None:
            document.metadata["relevance_score"] = round(score, 4)
        if (
            score is not None and score > relevance_threshold
        ) or _answer_uses_chunk(answer, document.page_content):
            cleaned_docs.append(document)

    cleaned_docs.sort(
        key=lambda document: document.metadata.get("relevance_score", 0),
        reverse=True,
    )
    return build_sources_from_docs(cleaned_docs)

def make_rag_chain(
    vectordb,
    k: int = None,
    answer_style: str = "short and crisp",
    filter_dict: dict = None,
    document_ids=None,
):
    """Build a LangChain Runnable that answers questions with source documents."""
    retriever, chosen_k = _build_retriever(
        vectordb, k=k, filter_dict=filter_dict, document_ids=document_ids
    )
    summary_k = k if k is not None else 20
    summary_retriever, _ = _build_retriever(
        vectordb,
        k=summary_k,
        filter_dict=filter_dict,
        document_ids=document_ids,
    )

    def retrieve_docs(question: str):
        if _is_summary_query(question):
            return summary_retriever.invoke(question)
        else:
            return retriever.invoke(question)

    llm = get_llm()
    rag_chain = (
        {
            "question": RunnablePassthrough(),
            "answer_style": lambda _: answer_style,
        }
        | RunnablePassthrough.assign(
            source_documents=lambda x: retrieve_docs(x["question"])
        )
        | RunnablePassthrough.assign(
            context=lambda x: build_context_from_docs(x["source_documents"])
        )
        | RunnablePassthrough.assign(
            prompt=lambda x: (
                SUMMARY_PROMPT if _is_summary_query(x["question"]) else FACTUAL_PROMPT
            ).format(
                context=x["context"],
                question=x["question"],
                answer_style=x["answer_style"],
                language_policy=LANGUAGE_POLICY,
            )
        )
        | RunnablePassthrough.assign(
            answer=lambda x: llm.invoke(x["prompt"]).content
        )
        | (lambda x: {
            "answer": x["answer"],
            "source_documents": x["source_documents"],
        })
    )

    return rag_chain, retriever, chosen_k