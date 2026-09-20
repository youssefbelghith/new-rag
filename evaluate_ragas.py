# evaluate.py
import os, json
import pandas as pd
from datasets import Dataset
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from rag_backend import (
    build_vectorstore_from_filepath,
    get_llm,
    get_embeddings,
    make_rag_chain,
)
from ragas import evaluate
from ragas.metrics import context_recall, answer_relevancy

PDF_PATH = r"C:\Users\Admin\Documents\GitHub\RAG\meta annual report.pdf"
OUTPUT_REPORT = "ragas_eval_report.json"
TEST_SIZE = 5

# ----------------------------------------------------------------------
# 1. Build vectorstore and RAG chain
# ----------------------------------------------------------------------
print("📄 Building vectorstore and RAG chain...")
vectordb = build_vectorstore_from_filepath(PDF_PATH)
rag_chain, retriever, _ = make_rag_chain(vectordb)

# ----------------------------------------------------------------------
# 2. Generate test questions + references from PDF pages
# ----------------------------------------------------------------------
print("📑 Loading PDF pages...")
loader = PyPDFLoader(PDF_PATH)
full_pages = loader.load()
full_pages = [p for p in full_pages if len(p.page_content.strip()) > 500]
selected_pages = full_pages[:TEST_SIZE]

llm = get_llm()

question_prompt = ChatPromptTemplate.from_template(
    """Based on the following page, generate ONE question answerable from the text.
Output ONLY the question, no extra text.
Page:
{page_content}
Question:"""
)
answer_prompt = ChatPromptTemplate.from_template(
    """Answer the question using ONLY the page content below.
Question: {question}
Page:
{page_content}
Answer:"""
)

questions, references, ref_contexts = [], [], []
for i, page in enumerate(selected_pages):
    page_text = page.page_content.strip()
    print(f"  Generating Q&A {i+1}/{TEST_SIZE}...")
    q = llm.invoke(question_prompt.format(page_content=page_text)).content.strip()
    a = llm.invoke(answer_prompt.format(page_content=page_text, question=q)).content.strip()
    questions.append(q)
    references.append(a)
    ref_contexts.append([page_text])

test_df = pd.DataFrame({
    "question": questions,
    "reference": references,
    "reference_contexts": ref_contexts,
})

# ----------------------------------------------------------------------
# 3. Run RAG pipeline
# ----------------------------------------------------------------------
print("🤖 Running RAG pipeline...")
retrieved_contexts, generated_answers = [], []
for q in test_df["question"]:
    docs = retriever.invoke(q)
    retrieved_contexts.append([d.page_content for d in docs])
    ans = rag_chain.invoke(q)
    generated_answers.append(getattr(ans, "content", str(ans)))

test_df["contexts"] = retrieved_contexts
test_df["answer"] = generated_answers
eval_dataset = Dataset.from_pandas(test_df)

# ----------------------------------------------------------------------
# 4. Evaluate using only the two working metrics
# ----------------------------------------------------------------------
print("📊 Evaluating...")
eval_llm = ChatOllama(model="llama3.1:8b", temperature=0, format="json")

result = evaluate(
    eval_dataset,
    metrics=[context_recall, answer_relevancy],
    llm=eval_llm,
    embeddings=get_embeddings(),
)

raw_recall = result["context_recall"]
raw_relevancy = result["answer_relevancy"]

result_dict = {
    "context_recall": sum(raw_recall) / len(raw_recall) if raw_recall else 0.0,
    "answer_relevancy": sum(raw_relevancy) / len(raw_relevancy) if raw_relevancy else 0.0,
}

final_report = {
    "overall_scores": result_dict,
    "per_question": test_df.to_dict(orient="records")
}
with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
    json.dump(final_report, f, indent=2, ensure_ascii=False)

print(f"✅ Done! Report saved to {OUTPUT_REPORT}")
for m, s in result_dict.items():
    print(f"  {m}: {s:.3f}")