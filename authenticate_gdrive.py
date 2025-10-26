
import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# --- Configuration ---
SCOPES = ["https://www.googleapis.com/auth/drive"]
CLIENT_SECRETS_FILE = "client_secret.json"
TOKEN_FILE = "gdrive_token.json"

def authenticate():
    """
    Performs OAuth 2.0 authentication for Google Drive API.
    This function is intended to be run once manually by the user.
    """
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)

    # The user will be prompted to authorize the application.
    # The authorization URL will be printed to the console.
    creds = flow.run_local_server(port=0)

    # Save the credentials for the next run
    with open(TOKEN_FILE, 'w') as token:
        token.write(creds.to_json())

    print(f"Authentication successful. Token saved to {TOKEN_FILE}")

if __name__ == "__main__":
    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"ERROR: Client secrets file not found at '{CLIENT_SECRETS_FILE}'")
        print("Please download it from Google Cloud Console and place it in the root directory.")
    else:
        authenticate()
