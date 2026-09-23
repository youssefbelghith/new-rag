import os
import tempfile
import time
import chromadb
from typing import List, Dict, Optional, Tuple
from functools import lru_cache

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
def build_vectorstore_from_files(file_bytes_list: List[Tuple[str, bytes]]):
    """Build a new vectorstore from a list of (filename, file_bytes) tuples."""
    if not file_bytes_list:
        raise ValueError("No files given.")

    tous_les_chunks = []

    for name, content in file_bytes_list:
        extension = name.split(".")[-1].lower()
        if extension not in ["pdf", "md", "markdown"]:
            continue

        # Write bytes to a temporary file for the loader
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{extension}")
        tmp.write(content)
        tmp.close()

        try:
            if extension == "pdf":
                loader = PyPDFLoader(tmp.name)
                docs = loader.load()
            else:
                docs = [Document(
                    page_content=content.decode("utf-8-sig", errors="replace"),
                    metadata={"source": name},
                )]
        finally:
            os.unlink(tmp.name)

        if not docs:
            continue

        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        chunks = splitter.split_documents(docs)

        for chunk in chunks:
            chunk.metadata["source"] = name

        tous_les_chunks.extend(chunks)

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
    except Exception:
        pass

    return vectordb

def add_single_file_to_vectorstore(uploaded_file, vectordb):
    """Add a single file (must have .name and .read()) to the existing vectorstore."""
    name = uploaded_file.name
    extension = name.split(".")[-1].lower()
    if extension not in ["pdf", "md", "markdown"]:
        return vectordb

    content = uploaded_file.read()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{extension}")
    tmp.write(content)
    tmp.close()

    try:
        if extension == "pdf":
            loader = PyPDFLoader(tmp.name)
            docs = loader.load()
        else:
            docs = [Document(
                page_content=content.decode("utf-8-sig", errors="replace"),
                metadata={"source": name},
            )]
    finally:
        os.unlink(tmp.name)

    if not docs:
        return vectordb

    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=150, add_start_index=True)
    chunks = splitter.split_documents(docs)

    for chunk in chunks:
        chunk.metadata["source"] = name

    vectordb.add_documents(documents=chunks)
    n_actuel = getattr(vectordb, "_n_chunks", 0)
    setattr(vectordb, "_n_chunks", n_actuel + len(chunks))

    return vectordb

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
def _build_retriever(vectordb, k: int = None, filter_dict: dict = None):
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
    if filter_dict:
        search_kwargs["filter"] = filter_dict

    return vectordb.as_retriever(
        search_type="mmr",
        search_kwargs=search_kwargs,
    ), chosen_k

def build_context_from_docs(docs):
    if not docs:
        return "No relevant context found in the document."
    return "\n\n-----\n\n".join(d.page_content for d in docs)

def build_sources_from_docs(docs):
    sources = []
    for d in docs:
        nom_fichier = d.metadata.get("source", "Unknown")
        sources.append({
            "fichier": nom_fichier,
            "page": d.metadata.get("page", 0) + 1,
        })
    return sources

def make_rag_chain(vectordb, k: int = None, answer_style: str = "short and crisp", filter_dict: dict = None):
    """Build a LangChain Runnable that answers questions with source documents."""
    retriever, chosen_k = _build_retriever(vectordb, k=k, filter_dict=filter_dict)
    summary_k = k if k is not None else 20
    summary_retriever, _ = _build_retriever(vectordb, k=summary_k, filter_dict=filter_dict)

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