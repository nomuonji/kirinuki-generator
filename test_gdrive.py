
import os
import json
import sys

def test_gdrive_credentials():
    """
    Isolates and tests the loading and parsing of the GDRIVE_CREDENTIALS_JSON
    environment variable to quickly diagnose issues.
    """
    print("--- Starting Google Drive Credentials Test ---")

    gdrive_creds_json = os.environ.get("GDRIVE_CREDENTIALS_JSON")

    if not gdrive_creds_json:
        print("ERROR: GDRIVE_CREDENTIALS_JSON environment variable not found.", file=sys.stderr)
        sys.exit(1)

    print("Successfully loaded GDRIVE_CREDENTIALS_JSON environment variable.")
    print("-" * 20)

    # --- Start Enhanced Debugging ---
    print("Running diagnostics on the loaded variable:")
    print(f"Type of gdrive_creds_json: {type(gdrive_creds_json)}")
    if isinstance(gdrive_creds_json, str):
        print(f"Length of gdrive_creds_json string: {len(gdrive_creds_json)}")
        print(f"First 20 chars: '{gdrive_creds_json[:20]}'")
        print(f"Last 20 chars: '{gdrive_creds_json[-20:]}'")
    else:
        print("gdrive_creds_json is not a string.")
    print("-" * 20)
    # --- End Enhanced Debugging ---

    try:
        print("Attempting to parse the variable as JSON...")
        json.loads(gdrive_creds_json)
        print("\n[SUCCESS] Successfully parsed GDRIVE_CREDENTIALS_JSON.")
        print("The content is a valid JSON string.")

    except json.JSONDecodeError as e:
        print(f"\n[FAILURE] Failed to parse GDRIVE_CREDENTIALS_JSON.", file=sys.stderr)
        print(f"Error details: {e}", file=sys.stderr)
        print("Please ensure the secret is a valid, single-line JSON string.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAILURE] An unexpected error occurred during parsing.", file=sys.stderr)
        print(f"Error type: {type(e).__name__}", file=sys.stderr)
        print(f"Error details: {e}", file=sys.stderr)
        sys.exit(1)

    print("\n--- Test Finished ---")

if __name__ == "__main__":
    test_gdrive_credentials()
