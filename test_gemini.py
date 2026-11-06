print("SCOUT TEST STARTED")

import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
print("Python packages loaded")

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("API KEY NOT FOUND - check your .env file")
else:
    print("API key found. Connecting to Gemini...")

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents="Say hello to SCOUT!"
    )

    print(response.text)