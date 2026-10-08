import os
import json
import secrets
import time
import requests
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pinecone import Pinecone as PineconeClient
from langchain_core.documents import Document

# Index Configuration
INDEX_NAME = os.environ.get('PINECONE_INDEX_NAME', 'demo-index')

# Global cached HTTP session with persistent connection pooling
_http_session = None

def get_http_session():
    global _http_session
    if _http_session is None:
        _http_session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=15,
            pool_maxsize=25,
            max_retries=2
        )
        _http_session.mount("https://", adapter)
        _http_session.mount("http://", adapter)
    return _http_session

# Global cached Pinecone Index client to avoid repeating costly control-plane calls
_pinecone_index_instance = None

def get_pinecone_index():
    global _pinecone_index_instance
    if _pinecone_index_instance is None:
        api_key = os.environ.get('PINECONE_API_KEY')
        if not api_key:
            return None
        pc = PineconeClient(api_key=api_key)
        _pinecone_index_instance = pc.Index(INDEX_NAME)
    return _pinecone_index_instance

def get_api_key():
    """Returns the Google Gemini API key from environment."""
    return os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY') or os.environ.get('OPENAI_API_KEY')

def check_credentials():
    """Checks if required API keys are present in the environment."""
    has_gemini = bool(get_api_key())
    has_pinecone = bool(os.environ.get('PINECONE_API_KEY'))
    return has_gemini and has_pinecone

class GeminiEmbeddings:
    """
    Lightweight, dependency-free Google Gemini Embeddings client using gemini-embedding-001.
    Produces 768-dimensional embeddings via Google AI Studio API with automatic 429 rate limit backoff.
    Reuses persistent HTTP sessions for minimal latency.
    """
    def __init__(self, api_key=None, model="gemini-embedding-001"):
        self.api_key = api_key or get_api_key()
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY (or GEMINI_API_KEY) environment variable is missing.")
        self.model = model
        self.endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:embedContent?key={self.api_key}"
        self.batch_endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents?key={self.api_key}"

    def embed_query(self, text: str):
        payload = {
            "model": f"models/{self.model}",
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": 768
        }
        session = get_http_session()
        max_retries = 3
        for attempt in range(max_retries):
            resp = session.post(self.endpoint, json=payload, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                return data["embedding"]["values"]
            elif resp.status_code == 429:
                wait_time = (2 ** attempt) * 2 + 1
                time.sleep(wait_time)
            else:
                raise RuntimeError(f"Gemini Embedding API Error ({resp.status_code}): {resp.text}")
        raise RuntimeError("Gemini Embedding rate limit exceeded for search query. Please wait a moment and try again.")

    def embed_documents(self, texts: list):
        if not texts:
            return []
        all_embeddings = []
        batch_size = 20
        max_retries = 4
        session = get_http_session()

        for i in range(0, len(texts), batch_size):
            chunk = texts[i:i + batch_size]
            payload = {
                "requests": [
                    {
                        "model": f"models/{self.model}",
                        "content": {"parts": [{"text": t}]},
                        "outputDimensionality": 768
                    }
                    for t in chunk
                ]
            }

            batch_succeeded = False
            for attempt in range(max_retries):
                resp = session.post(self.batch_endpoint, json=payload, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data.get("embeddings", []):
                        all_embeddings.append(item["values"])
                    batch_succeeded = True
                    break
                elif resp.status_code == 429:
                    wait_time = (2 ** attempt) * 2 + 1  # 3s, 5s, 9s, 17s
                    time.sleep(wait_time)
                else:
                    raise RuntimeError(f"Gemini Batch Embedding API Error ({resp.status_code}): {resp.text}")

            if not batch_succeeded:
                raise RuntimeError(
                    "Gemini API rate limit reached (30,000 tokens/minute on free tier). "
                    "Please wait a moment before uploading large files, or split the document into smaller parts."
                )

            # Only pause between batches if more than one batch is needed
            if i + batch_size < len(texts):
                time.sleep(0.3)

        return all_embeddings

class GeminiLLM:
    """
    Ultra-fast Google Gemini LLM client for answering questions based on document context.
    Prioritizes low-latency gemini-flash-lite-latest with fallback to gemini-flash-latest.
    Supports both synchronous and SSE token streaming.
    """
    MODELS = ["gemini-flash-lite-latest", "gemini-flash-latest"]

    def __init__(self, api_key=None):
        self.api_key = api_key or get_api_key()
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY (or GEMINI_API_KEY) environment variable is missing.")

    def _build_payload(self, query: str, context_documents: list):
        context_parts = []
        for i, doc in enumerate(context_documents):
            source = doc.metadata.get("filename") or os.path.basename(doc.metadata.get("source", "")) or f"Document {i+1}"
            context_parts.append(f"--- Document Source: {source} ---\n{doc.page_content}")
            
        context_text = "\n\n".join(context_parts)
        prompt = (
            "You are Quicks AI, an intelligent, helpful document assistant. "
            "Answer the user's question accurately and concisely based strictly on the provided document excerpts. "
            "If the answer cannot be found in the context, clearly explain that the uploaded documents do not contain that information.\n\n"
            f"Context Documents:\n{context_text}\n\n"
            f"User Question: {query}\n\n"
            "Answer:"
        )

        return {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1024
            }
        }

    def answer_question(self, query: str, context_documents: list):
        payload = self._build_payload(query, context_documents)
        session = get_http_session()
        last_error = None

        for model in self.MODELS:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            try:
                resp = session.post(endpoint, json=payload, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"].strip()
                else:
                    last_error = f"Model {model} returned {resp.status_code}: {resp.text}"
            except Exception as e:
                last_error = str(e)

        if last_error:
            raise RuntimeError(f"Gemini API Error: {last_error}")
        return "Unable to generate an answer from the document context."

    def stream_question(self, query: str, context_documents: list):
        """Streams answer tokens in real-time using Gemini SSE endpoint."""
        payload = self._build_payload(query, context_documents)
        session = get_http_session()

        for model in self.MODELS:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse&key={self.api_key}"
            try:
                resp = session.post(endpoint, json=payload, stream=True, timeout=25)
                if resp.status_code == 200:
                    streamed_any = False
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        line_str = line.decode('utf-8') if isinstance(line, bytes) else line
                        if line_str.startswith('data: '):
                            try:
                                data = json.loads(line_str[6:])
                                candidates = data.get('candidates', [])
                                if candidates and 'content' in candidates[0]:
                                    parts = candidates[0]['content'].get('parts', [])
                                    for part in parts:
                                        if 'text' in part and part['text']:
                                            streamed_any = True
                                            yield part['text']
                            except Exception:
                                continue
                    if streamed_any:
                        return
            except Exception:
                continue

        # Fallback to synchronous generation if streaming was unavailable
        yield self.answer_question(query, context_documents)

class SimplePineconeVectorStore:
    """
    Pinecone Vector Store wrapper providing multi-tenancy scoping and zero-dependency integration.
    Compatible with Python 3.14, Vercel Serverless, and Gemini 768-dimensional embeddings.
    """
    def __init__(self, index_name, embeddings, namespace):
        self.index_name = index_name
        self.embeddings = embeddings
        self.namespace = namespace
        self.index = get_pinecone_index()

    @classmethod
    def from_documents(cls, docs, embeddings, index_name, namespace):
        index = get_pinecone_index()
        if not index:
            raise ValueError("Pinecone index could not be initialized. Please check PINECONE_API_KEY.")
            
        # Batch embed document chunks via Gemini
        texts_to_embed = [doc.page_content for doc in docs]
        embedded_vectors = embeddings.embed_documents(texts_to_embed)
        
        vectors_to_upsert = []
        for i, (doc, embedding) in enumerate(zip(docs, embedded_vectors)):
            source_path = doc.metadata.get("source", "")
            base_filename = os.path.basename(source_path) if source_path else ""
            vector_id = f"{namespace}_{i}_{secrets.token_hex(4)}"
            metadata = {
                "text": doc.page_content,
                "source": source_path,
                "filename": base_filename
            }
            vectors_to_upsert.append((vector_id, embedding, metadata))
            
            # Upsert in batches of 100
            if len(vectors_to_upsert) >= 100:
                index.upsert(vectors=vectors_to_upsert, namespace=namespace)
                vectors_to_upsert = []
                
        if vectors_to_upsert:
            index.upsert(vectors=vectors_to_upsert, namespace=namespace)
            
        return cls(index_name, embeddings, namespace)

    @classmethod
    def from_existing_index(cls, index_name, embedding, namespace):
        return cls(index_name, embedding, namespace)

    def similarity_search(self, query, k=3):
        query_vector = self.embeddings.embed_query(query)
        response = self.index.query(
            namespace=self.namespace,
            vector=query_vector,
            top_k=k,
            include_metadata=True
        )
        
        docs = []
        for match in response.get("matches", []):
            metadata = match.get("metadata", {})
            text = metadata.pop("text", "")
            doc = Document(page_content=text, metadata=metadata)
            docs.append(doc)
        return docs

def get_embeddings():
    """Initializes and returns Gemini Embeddings."""
    return GeminiEmbeddings()

def get_llm():
    """Initializes and returns Gemini LLM client."""
    return GeminiLLM()

def load_documents(directory, filename):
    """Loads a single document (PDF or Text) from directory."""
    filepath = os.path.join(directory, filename)
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    
    if ext == 'pdf':
        loader = PyPDFLoader(filepath)
    else:
        loader = TextLoader(filepath, encoding='utf-8')
        
    return loader.load()

def split_documents(documents, chunk_size=1000, chunk_overlap=20):
    """Splits documents into smaller chunks."""
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    return text_splitter.split_documents(documents)

def save_embeddings(docs, user_id):
    """Saves document embeddings to Pinecone index under the user's namespace."""
    if not check_credentials():
        raise ValueError("Credentials for Gemini/Pinecone are not configured in environment.")
    
    embeddings = get_embeddings()
    namespace = f"user_{user_id}"
    
    SimplePineconeVectorStore.from_documents(
        docs, 
        embeddings, 
        index_name=INDEX_NAME, 
        namespace=namespace
    )
    return True

def query_index(query, user_id, k=3):
    """Queries the Pinecone index scoped to the user's namespace."""
    if not check_credentials():
        raise ValueError("Credentials for Gemini/Pinecone are not configured in environment.")
        
    embeddings = get_embeddings()
    namespace = f"user_{user_id}"
    
    vectorstore = SimplePineconeVectorStore.from_existing_index(
        index_name=INDEX_NAME, 
        embedding=embeddings, 
        namespace=namespace
    )
    return vectorstore.similarity_search(query, k=k)

def get_answer(query, user_id):
    """Executes RAG flow to fetch answer scoped to user's documents using Gemini."""
    if not check_credentials():
        return "Configuration Error: Google Gemini API key (GOOGLE_API_KEY) or Pinecone API key (PINECONE_API_KEY) is missing. Please set them in your environment variables."
        
    try:
        similar_docs = query_index(query, user_id)
        if not similar_docs:
            return "I couldn't find any relevant information in your uploaded documents. Please upload some files first!"
            
        llm = get_llm()
        answer = llm.answer_question(query, similar_docs)
        return answer
    except Exception as e:
        return f"An error occurred while answering: {str(e)}"

def stream_answer(query, user_id):
    """Executes RAG flow and yields streaming answer tokens scoped to user's documents using Gemini."""
    if not check_credentials():
        yield "Configuration Error: Google Gemini API key or Pinecone API key is missing. Please set them in your environment variables."
        return
        
    try:
        similar_docs = query_index(query, user_id)
        if not similar_docs:
            yield "I couldn't find any relevant information in your uploaded documents. Please upload some files first!"
            return
            
        llm = get_llm()
        for token in llm.stream_question(query, similar_docs):
            yield token
    except Exception as e:
        yield f"An error occurred while answering: {str(e)}"

def delete_user_file_embeddings(filename, user_id):
    """Deletes embeddings associated with a specific file from the user's Pinecone namespace."""
    if not check_credentials():
        return False
    try:
        index = get_pinecone_index()
        if not index:
            return False
        
        filepath = os.path.join('./static/uploads', f'user_{user_id}', filename)
        filepath_alt = filepath.replace('\\', '/')
        tmp_path = os.path.join('/tmp/quicks_uploads', f'user_{user_id}', filename)
        tmp_path_alt = tmp_path.replace('\\', '/')
        
        # Delete by filename filter
        try:
            index.delete(
                filter={"filename": {"$eq": filename}}, 
                namespace=f"user_{user_id}"
            )
        except Exception:
            pass

        # Also delete by source path filter (for backwards compatibility)
        try:
            index.delete(
                filter={"source": {"$in": [filepath, filepath_alt, tmp_path, tmp_path_alt, filename]}}, 
                namespace=f"user_{user_id}"
            )
        except Exception:
            pass

        return True
    except Exception as e:
        print(f"Error deleting embeddings for {filename}: {e}")
        return False
