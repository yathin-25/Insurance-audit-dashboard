# Local setup (Windows PowerShell / macOS / Linux)

1. Install Python 3.11+ (python.org) and confirm: python --version
2. In this folder:
   python -m venv .venv
   Windows:  .venv\Scripts\Activate.ps1      macOS/Linux:  source .venv/bin/activate
   pip install -r requirements.txt
3. Run the tests (all should pass):
   pytest -q
4. Set environment (PowerShell):
   $env:ENVIRONMENT="development"; $env:JWT_SECRET="<32+ random chars>"
   (macOS/Linux: export ENVIRONMENT=development JWT_SECRET=...)
5. Create users (prompts for password, min 12 chars, mixed case + digit):
   python -m scripts.create_user --username admin1 --role admin
   python -m scripts.create_user --username analyst1 --role analyst
6. Generate SYNTHETIC data:
   python -m scripts.generate_synthetic --rows 500 --out sample_data/synthetic_claims.csv
7. Start the API:
   uvicorn app.main:app --reload
   Open http://127.0.0.1:8000/docs (login at POST /auth/login, then Authorize with the token)
8. Upload sample_data/synthetic_claims.csv with data_origin=synthetic, then
   POST /datasets/{id}/evaluate, then explore /runs/{run_id}.
