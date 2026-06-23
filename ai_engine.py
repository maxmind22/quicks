import os
import secrets
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_classic.chains.question_answering import load_qa_chain
from pinecone import Pinecone as PineconeClient
from langchain_core.documents import Document

# Index Configuration
INDEX_NAME = 'demo-index'

class SimplePineconeVectorStore:
    """
    A custom Pinecone Vector Store wrapper to replace langchain-pinecone.
    Provides compatibility for modern Python environments (like Python 3.14) 
    without heavy C-extensions or deprecated community integrations.
    """
    def __init__(self, index_name, embeddings, namespace):
        self.index_name = index_name
        self.embeddings = embeddings
        self.namespace = namespace
        pc = PineconeClient(api_key=os.environ.get('PINECONE_API_KEY'))
        self.index = pc.Index(index_name)

    @classmethod
    def from_documents(cls, docs, embeddings, index_name, namespace):
        pc = PineconeClient(api_key=os.environ.get('PINECONE_API_KEY'))
        
        # Verify index exists
        if index_name not in pc.list_indexes().names():
            raise ValueError(
                f"Pinecone index '{index_name}' was not found. "
                "Please create it on your Pinecone dashboard with 1536 dimensions and cosine metric."
            )
            
        index = pc.Index(index_name)
        
        # Batch embed and upsert document chunks
        vectors_to_upsert = []
        for i, doc in enumerate(docs):
            # Compute embeddings via OpenAI
            embedding = embeddings.embed_query(doc.page_content)
            
            # Generate unique ID and bundle metadata
            vector_id = f"{namespace}_{i}_{secrets.token_hex(4)}"
            metadata = {
                "text": doc.page_content,
                "source": doc.metadata.get("source", "")
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
        # Embed query text
        query_vector = self.embeddings.embed_query(query)
        
        # Query Pinecone
        response = self.index.query(
            namespace=self.namespace,
            vector=query_vector,
            top_k=k,
            include_metadata=True
        )
        
        # Convert Pinecone results to LangChain Document objects
        docs = []
        for match in response.get("matches", []):
            metadata = match.get("metadata", {})
            text = metadata.pop("text", "")
            doc = Document(page_content=text, metadata=metadata)
            docs.append(doc)
        return docs


def check_credentials():
    """Checks if required API keys are present in the environment."""
    return bool(os.environ.get('OPENAI_API_KEY') and os.environ.get('PINECONE_API_KEY'))

def get_embeddings():
    """Initializes and returns OpenAI Embeddings."""
    if not os.environ.get('OPENAI_API_KEY'):
        raise ValueError("OPENAI_API_KEY environment variable is missing.")
    return OpenAIEmbeddings(model='text-embedding-ada-002')

def get_llm():
    """Initializes and returns ChatOpenAI model."""
    if not os.environ.get('OPENAI_API_KEY'):
        raise ValueError("OPENAI_API_KEY environment variable is missing.")
    return ChatOpenAI(model='gpt-3.5-turbo')

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
        raise ValueError("Credentials for OpenAI/Pinecone are not configured in environment.")
    
    embeddings = get_embeddings()
    namespace = f"user_{user_id}"
    
    # Save documents using our custom vector store wrapper
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
        raise ValueError("Credentials for OpenAI/Pinecone are not configured in environment.")
        
    embeddings = get_embeddings()
    namespace = f"user_{user_id}"
    
    vectorstore = SimplePineconeVectorStore.from_existing_index(
        index_name=INDEX_NAME, 
        embedding=embeddings, 
        namespace=namespace
    )
    return vectorstore.similarity_search(query, k=k)

def get_answer(query, user_id):
    """Executes RAG flow to fetch answer scoped to user's documents."""
    if not check_credentials():
        return "Configuration Error: OpenAI or Pinecone API keys are missing. Please set them in your environment variables."
        
    try:
        similar_docs = query_index(query, user_id)
        if not similar_docs:
            return "I couldn't find any relevant information in your uploaded documents. Please upload some files first!"
            
        llm = get_llm()
        chain = load_qa_chain(llm, chain_type="stuff")
        answer = chain.run(input_documents=similar_docs, question=query)
        return answer
    except Exception as e:
        return f"An error occurred while answering: {str(e)}"

def delete_user_file_embeddings(filename, user_id):
    """Deletes embeddings associated with a specific file from the user's Pinecone namespace."""
    if not check_credentials():
        return False
    try:
        pc = PineconeClient(api_key=os.environ.get('PINECONE_API_KEY'))
        index = pc.Index(INDEX_NAME)
        
        # Files are saved in './static/uploads/user_<id>/filename'
        filepath = os.path.join('./static/uploads', f'user_{user_id}', filename)
        filepath_alt = filepath.replace('\\', '/')
        
        # Filter vectors by source metadata matching the file path
        index.delete(
            filter={"source": {"$in": [filepath, filepath_alt]}}, 
            namespace=f"user_{user_id}"
        )
        return True
    except Exception as e:
        print(f"Error deleting embeddings for {filename}: {e}")
        return False
