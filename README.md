# Customer Support AI Agent

## Run locally (Windows PowerShell)

Follow these steps from the repository root. The application stores policy
chunks in MongoDB Atlas; operational records and customer/support-agent
accounts remain in local JSON files under `data/`. MongoDB is a database
service, not a JSON file in the repository.

### 1. Install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Set-Location frontend
npm install
Set-Location ..
```

### 2. Configure credentials and MongoDB Atlas

Create `.env` from the template if it does not exist:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Set `GROQ_API_KEY`, `MISTRAL_API_KEY`, `MONGODB_URI`, and
`MONGODB_DATABASE` in `.env`. Keep this file private and do not commit it.
`STORAGE_BACKEND` defaults to `mongodb`; the default search index names are
`policy_vector_index` and `policy_bm25_index`.

In Atlas, allow your development IP address and create a database user with
read/write access to the configured database. The application writes only
policy chunks to the `policychunks` collection. Customer and support-agent
accounts, orders, tickets, and other operational data stay in local JSON files.

### 3. Create login accounts

Create a customer account for a customer ID present in `data/orders.json`:

```powershell
.\.venv\Scripts\python.exe -m app.services.customer_accounts --customer-id CUS-DEMO-001 --email customer@example.com
```

Create a separate support-agent account:

```powershell
.\.venv\Scripts\python.exe -m app.services.support_agent_accounts --staff-id STAFF-001 --email agent@example.com
```

Enter and confirm each password when prompted; passwords must be 12–256
characters. Account hashes are stored in `data/customer_accounts.json` and
`data/support_agents.json`. Customer and support-agent logins are separate.

### 4. Ingest the policy PDF

With MongoDB and Mistral configured, run this from the repository root:

```powershell
.\.venv\Scripts\python.exe -m app.rag.ingestion
```

This semantically chunks `data/policies/Policies.pdf`, creates Mistral
embeddings, and replaces that document's chunks in MongoDB's `policychunks`
collection.

### 5. Create both Atlas search indexes

After ingestion creates the `policychunks` collection, create both indexes in
Atlas and wait for each to show **Ready**. They are separate index types.

#### Vector Search index

Create a Vector Search index named `policy_vector_index` on `policychunks`:

```json
{
  "fields": [
    {"type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine"},
    {"type": "filter", "path": "document_id"},
    {"type": "filter", "path": "embedding_model"},
    {"type": "filter", "path": "metadata.approved"},
    {"type": "filter", "path": "metadata.updated_at"}
  ]
}
```

#### Atlas Search (BM25) index

Separately, create an Atlas Search index named `policy_bm25_index` on
`policychunks` with this static mapping:

```json
{
  "mappings": {
    "dynamic": false,
    "fields": {
      "text": {"type": "string", "analyzer": "lucene.standard"},
      "title": {"type": "string", "analyzer": "lucene.standard"},
      "document_id": {"type": "token"},
      "metadata": {
        "type": "document",
        "fields": {
          "approved": {"type": "boolean"},
          "updated_at": {"type": "token"}
        }
      }
    }
  }
}
```

### 6. Start the application

Open two PowerShell windows at the repository root.

In the first window, start the API:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

In the second window, start the frontend:

```powershell
Set-Location frontend
npm run dev
```

Open the local URL printed by Vite. Customers sign in at the main page with
their customer account. Support staff sign in at
`http://127.0.0.1:5173/admin/dashboard` with their support-agent account.
The API health check is `http://127.0.0.1:8000/health`.
