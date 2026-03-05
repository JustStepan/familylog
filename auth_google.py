"""
Одноразовая авторизация Google Calendar.
Запуск: uv run auth_google.py
Результат: calendar_token.json — сохраняется автоматически. (добавляем в гитигнор)
необходимы библиотеки uv add google-auth-oauthlib и далее для интеграции google-auth-httplib2 google-api-python-client  
"""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
CREDENTIALS_FILE = "calendar_credentials.json"
TOKEN_FILE = "calendar_token.json"

def main():
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())
    
    print(f"✅ Токен сохранён в {TOKEN_FILE}")
    print("Добавь calendar_token.json в .gitignore!")

if __name__ == "__main__":
    main()