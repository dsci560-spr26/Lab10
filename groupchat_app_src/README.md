Group Chat Web App + LLM Bot (Ollama Integration)

FastAPI + MySQL + vanilla HTML/JS group chat with an integrated LLM bot. This project has been upgraded to use a self-hosted Ollama server instead of llama.cpp for better stability and performance.

Quick Start (Dev Environment)

1. Database Setup (MySQL)

Ensure MySQL is running on your machine. Create the database and user:

CREATE DATABASE groupchat;
CREATE USER 'chatuser'@'localhost' IDENTIFIED BY 'chatpass';
GRANT ALL PRIVILEGES ON groupchat.* TO 'chatuser'@'localhost';
FLUSH PRIVILEGES;


2. Backend Setup

Navigate to the backend directory and set up the Python virtual environment:

cd backend
python3 -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
pip install -r requirements.txt
pip install httpx  # Required for LLM API connection


3. Environment Variables

Create a new .env file inside the backend directory (do NOT commit this file to version control) and add the following configuration:

DATABASE_URL=mysql+asyncmy://chatuser:chatpass@localhost:3306/groupchat
JWT_SECRET=your_super_secret_random_string_here
JWT_EXPIRE_MINUTES=43200
LLM_API_BASE=[http://127.0.0.1:11434](http://127.0.0.1:11434)
LLM_MODEL=llama3.1:8b
APP_HOST=0.0.0.0
APP_PORT=8000


4. LLM Bot Setup (Ollama)

This project uses Ollama to host the LLM locally.

Download and install Ollama.

Pull the required model:

ollama pull llama3.1:8b


Start the Ollama service in a separate terminal:

ollama serve


5. Run the Application

Start the FastAPI backend server:

python -m uvicorn app:app --host 0.0.0.0 --port 8000


Open http://localhost:8000 in your browser. Any message ending with a ? will automatically trigger the LLM Bot to reply in the chat.

Part 2: Android TWA (For Mobile Developers)

To build the Android Trusted Web Activity (TWA):

Open the twa_android_src folder in Android Studio.

Navigate to app/src/main/res/values/strings.xml and update the defaultUrl:

For Android Emulator: http://10.0.2.2:8000

For physical device: Use your computer's local network IP (e.g., http://192.168.X.X:8000).

Generate your SHA-256 fingerprint via keytool and create the assetlinks.json file.

Place the assetlinks.json file in the Web server's /.well-known/ directory to successfully hide the Chrome address bar.