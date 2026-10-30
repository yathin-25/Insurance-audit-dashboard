<img width="960" height="474" alt="Screenshot 2026-10-29 105949" src="https://github.com/user-attachments/assets/76f15cd6-106b-4007-817f-89144579c106" />
<img width="960" height="513" alt="Screenshot 2026-10-29 112058" src="https://github.com/user-attachments/assets/d04adfb7-1211-4f2b-9607-b0b4147e2b01" />
<img width="960" height="509" alt="Screenshot 2026-10-29 112102" src="https://github.com/user-attachments/assets/d8bbe4b9-c78e-4c4a-ab51-5a66f667f9f3" />

# 🛡️ Enterprise Insurance Audit & Compliance Dashboard

An enterprise-grade, full-stack insurance audit and compliance dashboard featuring a rule-based deterministic risk engine paired with a modern React frontend for real-time claim analytics, automated data underwriting, and circuit breaker metrics.

---

## 📸 Dashboard Preview

*Drop your screenshots inside a `screenshots/` folder in your project repository, and they will render right here on your GitHub page!*

### 1. Main Dashboard & Analytics Overview
![Dashboard Overview](screenshots/dashboard-overview.png)

### 2. Claims Underwriting & Risk Evaluation
![Claims Underwriting](screenshots/claims-underwriting.png)

---

## 🚀 Key Features

* **Deterministic Risk Engine:** Built with FastAPI and Pydantic to evaluate claims accuracy based on 9 distinct operational metrics.
* **Real-time Data Ingestion:** Upload and process real-world CSV claim files with automated compliance checks.
* **Interactive Frontend:** Developed using React, TypeScript, and Tailwind CSS for a seamless, responsive analytics experience.
* **Security & Circuit Breakers:** Integrated rate limiting, secure private file storage, and automated compliance auditing workflows.

---

## 🛠️ Tech Stack

* **Backend:** Python, FastAPI, Pydantic, Pytest, SQLite
* **Frontend:** React, TypeScript, Vite, Tailwind CSS
* **Architecture:** RESTful API services with modular auditing and metrics engines

---

## ⚙️ Quick Start (Local Development)

### 1. Backend Setup
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
