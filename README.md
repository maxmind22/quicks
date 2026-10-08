# ⚡ Quicks — AI Document Search

🔗 **Live Deployment:** [https://quicks.mpeka.rw](https://quicks.mpeka.rw)

Quicks is a modern, responsive, and secure Retrieval-Augmented Generation (RAG) web application. It enables users to upload document collections (PDFs, text files) and run semantic query searches to get immediate, context-aware answers from their own data.

Designed with a premium **dark-themed glassmorphism** user interface and built-in **multi-tenancy security**, it keeps document collections and query vectors completely isolated between different user spaces.

---

## ✨ Key Features

* **🔒 Secure Multi-Tenancy**: Fully isolated user registration and login. Files are stored in user-specific directories and vectors are scoped in Pinecone using isolated user namespaces.
* **📂 Document Management**: Upload PDF and text files directly on your dashboard. View your document inventory with dynamic file icons and delete them securely (clearing their files and database vector indexes).
* **💬 Modern Chat Interface**: Interactive chat window showing user queries and streaming LLM responses with micro-animations and typing indicators.
* **🧪 Stable Custom Integrations**: Deployed with a custom Pinecone vector store wrapper to assure 100% package compatibility and crash-free launches, even under newer Python runtimes (like Python 3.14).
* **🎨 Glassmorphic Layout**: Dark theme featuring background blurs, glowing gradients, Inter typography, and clean navigation menus.

---

## 🛠️ Technology Stack

* **Backend**: Flask, Flask-Login, Flask-SQLAlchemy (SQLite database), WTForms
* **AI/RAG Engine**: Google Gemini API (`gemini-embedding-001` with 768 dimensions & `gemini-flash`), Pinecone Vector Database, LangChain document loaders
* **Frontend**: HTML5, Vanilla CSS3 (Custom Glassmorphism system), Bootstrap 5.3.0, FontAwesome 6, jQuery AJAX

---

## 🚀 Quick Start Guide

Follow these steps to set up and run the application locally on your machine.

### 1. Clone the Project
```bash
git clone https://github.com/maxmind22/quicks.git
cd quicks
```

### 2. Set Up Virtual Environment & Dependencies
Create a virtual environment to manage dependencies:
```bash
python -m venv venv

# On Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# On macOS/Linux:
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### 3. Configure Environment Variables
You need to set up your API keys to enable embedding generation and OpenAI chat queries. 

**On Windows (PowerShell):**
```powershell
$env:GEMINI_API_KEY="your-gemini-api-key"
$env:PINECONE_API_KEY="your-pinecone-api-key"
$env:PINECONE_ENVIRONMENT="your-pinecone-environment-name"
```

**On macOS/Linux:**
```bash
export GEMINI_API_KEY="your-gemini-api-key"
export PINECONE_API_KEY="your-pinecone-api-key"
export PINECONE_ENVIRONMENT="your-pinecone-environment-name"
```

> [!NOTE]
> The server will start and run cleanly even if these credentials are not set. The dashboard will show a warning alert explaining that API keys are missing.

### 4. Run the Application
Start the Flask development server:
```bash
python main.py
```
Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your web browser to test and interact with the app.

---

## ⚡ Deploy to Vercel

Quicks is configured for 1-click deployment on Vercel via Serverless Functions.

### 1. Push your code to GitHub
```bash
git add .
git commit -m "Configure Vercel serverless deployment"
git push origin master
```

### 2. Import into Vercel
1. Go to [vercel.com](https://vercel.com) and click **"Add New Project"**.
2. Select your `quicks` repository.
3. Keep the default settings (Vercel will detect the Python runtime via `vercel.json` and `api/index.py`).

### 3. Configure Environment Variables in Vercel
Under **Project Settings > Environment Variables**, add:
* `SECRET_KEY`: A random secure string for session encryption.
* `DATABASE_URL`: A PostgreSQL database connection string (e.g. from [Neon](https://neon.tech) or [Supabase](https://supabase.com)).
* `GEMINI_API_KEY`: Your Google Gemini API key (from [Google AI Studio](https://aistudio.google.com/)).
* `PINECONE_API_KEY`: Your Pinecone API key.
* `PINECONE_ENVIRONMENT`: Your Pinecone index region/environment name.

---

## 📁 Repository Structure
```text
quicks/
│
├── static/
│   ├── css/
│   │   └── styles.css       # Glassmorphism design tokens & styles
│   └── js/
│       ├── script.js        # Chat logic & AJAX query handling
│       └── alert.js         # Safe alert dismiss controls
│
├── templates/
│   ├── base.html            # Main template (Bootstrap 5 & fonts)
│   ├── index.html           # Welcome landing page
│   ├── login.html           # Login card form
│   ├── register.html        # Registration card form
│   ├── upload.html          # Document uploading screen
│   └── dashboard.html       # Split panel (My Documents & AI Chat)
│
├── ai_engine.py             # Custom Pinecone RAG engine & document loaders
├── decorators.py            # Login-redirection decorators
├── forms.py                 # WTForms layout specifications
├── main.py                  # Main Flask application & route actions
└── requirements.txt         # Project package requirements
```
