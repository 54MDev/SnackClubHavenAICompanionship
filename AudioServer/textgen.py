from google import genai

# Automatically uses the GEMINI_API_KEY environment variable
client = genai.Client()

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Explain how quantum computing works in two sentences.",
)

print(response.text)
