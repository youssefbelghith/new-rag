import os
import re
import tempfile
import time
from typing import List, Optional, Dict

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr, Field, field_validator

# Existing DB utilities (unchanged)
from db_utils import (
    create_user, authenticate_user, get_user_info, ensure_history_schema, create_chat_session,
    get_chat_sessions, get_chat_session, update_chat_session,
    delete_chat_session, get_chat_session_detail, save_chat_messages, update_user_avatar
)

# RAG logic (rewritten without Streamlit)
from rag_backend import (
    build_vectorstore_from_files,
    add_single_file_to_vectorstore,
    answer_general_question,
    make_rag_chain,
    get_closest_sources,
    get_embeddings
)

# JWT / password hashing
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta

# ========== CONFIG ==========
SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# ========== MODELS ==========
class UserCreate(BaseModel):
    nom: str
    prenom: str
    email: EmailStr
    password: str = Field(min_length=8)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value):
        if not value.strip():
            raise ValueError("Password cannot be empty or whitespace-only")
        if not re.search(r"[A-Za-z]", value) or not re.search(r"[0-9]", value):
            raise ValueError("Password must contain at least one letter and one number")
        return value

class UserLogin(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip() if isinstance(value, str) else value

class AvatarUpdate(BaseModel):
    avatar: str

class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: int
    prenom: str
    email: str

class AskRequest(BaseModel):
    question: str
    session_id: str
    filter_dict: Optional[Dict] = None
    answer_style: str = "short and crisp"

class Source(BaseModel):
    fichier: str
    page: int

class AnswerResponse(BaseModel):
    answer: str
    sources: List[Source]

class ConversationExchange(BaseModel):
    question: str
    answer: str
    sources: List[Source] = Field(default_factory=list)

class ConversationFile(BaseModel):
    name: str
    timestamp: Optional[str] = None

class ConversationSaveRequest(BaseModel):
    session_id: str
    exchanges: List[ConversationExchange] = Field(default_factory=list)
    files: List[ConversationFile] = Field(default_factory=list)

class SessionCreateRequest(BaseModel):
    title: str = "New conversation"
    model_settings: Dict = Field(default_factory=dict)
    session_id: Optional[str] = None

class SessionUpdateRequest(BaseModel):
    title: Optional[str] = None
    model_settings: Optional[Dict] = None

# ========== IN‑MEMORY STORAGE (per user) ==========
# structure: user_id -> {"vectordb": Chroma, "files": List[str]}
USER_VECTORSTORES: Dict[tuple, Dict] = {}

# ========== AUTH HELPERS ==========
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme)) -> int:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        return int(user_id)
    except (JWTError, TypeError, ValueError):
        raise credentials_exception

# ========== APP INIT ==========
app = FastAPI(title="RAG Chat API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def initialize_database_schema():
    ensure_history_schema()

# ========== ENDPOINTS ==========
@app.post("/signup", response_model=Token)
async def signup(user: UserCreate):
    """Create new user and return token."""
    try:
        user_id = create_user(user.nom, user.prenom, user.email, user.password)
    except Exception as e:
        if "Duplicate entry" in str(e):
            raise HTTPException(status_code=400, detail="Email already registered")
        raise HTTPException(status_code=500, detail=str(e))

    token = create_access_token({"sub": str(user_id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user_id,
        "prenom": user.prenom,
        "email": user.email
    }

@app.post("/login", response_model=Token)
async def login(user: UserLogin):
    """Authenticate user and return token."""
    result = authenticate_user(user.email, user.password)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    uid, nom, prenom, email = result
    token = create_access_token({"sub": str(uid)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": uid,
        "prenom": prenom,
        "email": email
    }

@app.get("/user/info")
async def user_info(user_id: int = Depends(get_current_user)):
    """Get user profile info."""
    info = get_user_info(user_id)
    if not info:
        raise HTTPException(status_code=404, detail="User not found")
    return info

@app.put("/user/avatar")
async def update_avatar(request: AvatarUpdate, user_id: int = Depends(get_current_user)):
    if not update_user_avatar(user_id, request.avatar):
        raise HTTPException(status_code=404, detail="User not found")
    return {"avatar": request.avatar}

@app.get("/user/conversations")
async def user_conversations(user_id: int = Depends(get_current_user), limit: int = 100):
    return get_chat_sessions(user_id, limit=limit)

@app.post("/user/sessions")
async def create_session(
    request: SessionCreateRequest,
    user_id: int = Depends(get_current_user)
):
    return create_chat_session(user_id, request.title, request.model_settings, request.session_id)

@app.get("/user/sessions")
async def list_sessions(user_id: int = Depends(get_current_user), limit: int = Query(100, ge=1, le=500)):
    return get_chat_sessions(user_id, limit=limit)

@app.patch("/user/sessions/{session_id}")
async def edit_session(
    session_id: str,
    request: SessionUpdateRequest,
    user_id: int = Depends(get_current_user)
):
    session = update_chat_session(user_id, session_id, request.title, request.model_settings)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session

@app.get("/user/sessions/{session_id}")
async def session_detail(session_id: str, user_id: int = Depends(get_current_user)):
    session = get_chat_session_detail(user_id, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session

@app.delete("/user/sessions/{session_id}")
async def remove_session(session_id: str, user_id: int = Depends(get_current_user)):
    if not delete_chat_session(user_id, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    USER_VECTORSTORES.pop((user_id, session_id), None)
    return {"message": "Session deleted"}

@app.post("/user/conversations/finalize")
async def finalize_conversation(
    request: ConversationSaveRequest,
    user_id: int = Depends(get_current_user)
):
    if not request.exchanges and not request.files:
        return {"message": "Nothing to save"}
    if not save_chat_messages(
        user_id=user_id,
        session_id=request.session_id,
        exchanges=[exchange.model_dump() for exchange in request.exchanges],
        files=[file.model_dump() for file in request.files],
    ):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"message": "Conversation saved"}

@app.get("/user/conversations/{conversation_id}")
async def conversation(
    conversation_id: str,
    user_id: int = Depends(get_current_user)
):
    session = get_chat_session_detail(user_id, conversation_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session

@app.post("/files/upload")
async def upload_files(
    files: List[UploadFile] = File(...),
    session_id: str = Query(...),
    user_id: int = Depends(get_current_user)
):
    """Process uploaded files and add to the user's vectorstore."""
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    # Read file contents into bytes (needed for processing)
    file_bytes_list = []
    for file in files:
        content = await file.read()
        file_bytes_list.append((file.filename, content))

    # Get or create user's vectorstore
    store_key = (user_id, session_id)
    user_store = USER_VECTORSTORES.get(store_key)
    if user_store is None:
        # First upload – build a new vectorstore from all files
        vectordb = build_vectorstore_from_files(file_bytes_list)
        processed_files = [name for name, _ in file_bytes_list]
        USER_VECTORSTORES[store_key] = {
            "vectordb": vectordb,
            "files": processed_files
        }
    else:
        # Add each file individually to existing vectorstore
        vectordb = user_store["vectordb"]
        for name, content in file_bytes_list:
            # Create a temporary UploadFile-like object for the backend function
            class FakeUploadFile:
                def __init__(self, name, content):
                    self.name = name
                    self._content = content
                def read(self):
                    return self._content
            fake_file = FakeUploadFile(name, content)
            vectordb = add_single_file_to_vectorstore(fake_file, vectordb)
            user_store["files"].append(name)
        USER_VECTORSTORES[store_key]["vectordb"] = vectordb

    return {"message": "Files processed successfully", "processed_files": [name for name, _ in file_bytes_list]}

@app.post("/ask", response_model=AnswerResponse)
async def ask_question(
    request: AskRequest,
    user_id: int = Depends(get_current_user)
):
    """Answer normally, or use the user's uploaded documents when available."""
    if not get_chat_session(user_id, request.session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    user_store = USER_VECTORSTORES.get((user_id, request.session_id))
    if user_store and user_store["vectordb"] is not None:
        vectordb = user_store["vectordb"]
        filter_dict = request.filter_dict

        rag_chain, _, _ = make_rag_chain(
            vectordb,
            answer_style=request.answer_style,
            filter_dict=filter_dict
        )
        result = rag_chain.invoke(request.question)
        answer = result["answer"]

        embed_model = get_embeddings()
        sources = get_closest_sources(answer, vectordb, embed_model, k=3)
    else:
        answer = answer_general_question(
            request.question,
            answer_style=request.answer_style,
        )
        sources = []

    return AnswerResponse(answer=answer, sources=sources)