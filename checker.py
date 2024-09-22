import os
import logging
import time
import json
from typing import Dict, List
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Define the scopes
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# Rate limiting constants
REQUESTS_PER_MINUTE = 50
SECONDS_PER_MINUTE = 60

# Monitoring constants
CHECK_INTERVAL = 10  # Check for changes every 10 seconds (adjust as needed)

# State file
STATE_FILE = 'sheet_state.json'

class RateLimiter:
    def __init__(self, max_calls, period):
        self.max_calls = max_calls
        self.period = period
        self.calls = []

    def __call__(self, f):
        def wrapped(*args, **kwargs):
            now = time.time()
            self.calls = [t for t in self.calls if now - t < self.period]
            if len(self.calls) >= self.max_calls:
                sleep_time = self.period - (now - self.calls[0])
                if sleep_time > 0:
                    logging.info(f"Rate limit reached. Sleeping for {sleep_time:.2f} seconds.")
                    time.sleep(sleep_time)
            self.calls.append(time.time())
            return f(*args, **kwargs)
        return wrapped

# Create a RateLimiter instance
rate_limiter = RateLimiter(REQUESTS_PER_MINUTE, SECONDS_PER_MINUTE)

def get_credentials():
    try:
        creds = service_account.Credentials.from_service_account_info({
            "type": os.getenv("GOOGLE_SERVICE_ACCOUNT_TYPE2"),
            "project_id": os.getenv("GOOGLE_PROJECT_ID2"),
            "private_key_id": os.getenv("GOOGLE_PRIVATE_KEY_ID2"),
            "private_key": os.getenv("GOOGLE_PRIVATE_KEY2").replace('\\n', '\n'),
            "client_email": os.getenv("GOOGLE_CLIENT_EMAIL2"),
            "client_id": os.getenv("GOOGLE_CLIENT_ID2"),
            "auth_uri": os.getenv("GOOGLE_AUTH_URI2"),
            "token_uri": os.getenv("GOOGLE_TOKEN_URI2"),
            "auth_provider_x509_cert_url": os.getenv("GOOGLE_AUTH_PROVIDER_X509_CERT_URL2"),
            "client_x509_cert_url": os.getenv("GOOGLE_CLIENT_X509_CERT_URL2")
        }, scopes=SCOPES)
    except Exception as e:
        logging.error(f"Error creating credentials: {str(e)}")
        raise
    
    return creds

@rate_limiter
def get_spreadsheet_ids(service, display_sheet_log_id: str) -> List[str]:
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=display_sheet_log_id,
            range="A:D"
        ).execute()
        values = result.get('values', [])
        
        if not values:
            logging.error("No data found in display_sheet_log.")
            return []

        spreadsheet_ids = [row[3] for row in values[1:] if len(row) > 3]
        return spreadsheet_ids

    except HttpError as error:
        logging.error(f"An error occurred while fetching spreadsheet IDs: {error}")
        raise

@rate_limiter
def get_sheet_data(service, spreadsheet_id: str) -> Dict[str, List]:
    try:
        sheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = sheet_metadata.get('sheets', '')
        
        sheet_data = {}
        for sheet in sheets:
            sheet_name = sheet['properties']['title']
            if sheet_name != "Setting":
                range_name = f"{sheet_name}!1:1"
                result = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
                values = result.get('values', [[]])[0]
                columns = [chr(65 + i) for i in range(len(values))]
                sheet_data[sheet_name] = columns
        
        return sheet_data
    except HttpError as error:
        logging.error(f"An error occurred while fetching sheet data for spreadsheet {spreadsheet_id}: {error}")
        raise

@rate_limiter
@rate_limiter
def update_setting_sheet(service, spreadsheet_id: str, sheet_data: Dict[str, List]) -> bool:
    try:
        sheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        setting_sheet = next((sheet for sheet in sheet_metadata.get('sheets', '') if sheet['properties']['title'] == "Setting"), None)
        
        if not setting_sheet:
            logging.error(f"The 'Setting' sheet does not exist in the spreadsheet with ID {spreadsheet_id}.")
            return False

        setting_sheet_range = "Setting!A1:Z1000"
        result = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=setting_sheet_range).execute()
        existing_data = result.get('values', [])
        new_data = [["sheet_name", "time_of_display (in sec)", "existing column", "columns in display", "display", "Title to display as", "photo column"]]

        # Build a map of existing data for easy lookup and modification
        existing_sheets = {row[0]: row for row in existing_data[1:] if len(row) >= 3}
        
        # Update existing entries or add new ones
        for sheet_name, columns in sheet_data.items():
            columns_string = ','.join(columns)
            if sheet_name in existing_sheets:
                # Update existing sheet data
                existing_row = existing_sheets[sheet_name]
                existing_row[2] = columns_string
                new_data.append(existing_row)
            else:
                # Add new sheet data
                new_data.append([sheet_name, "10", columns_string, "", "last 5 row", "", ""])

        # Remove sheets that no longer exist
        sheets_to_remove = set(existing_sheets.keys()) - set(sheet_data.keys())
        for sheet_name in sheets_to_remove:
            logging.info(f"Removed sheet '{sheet_name}' from Setting sheet")

        # Log the new data being sent to the 'Setting' sheet for debugging
        logging.info(f"New data to be written to the 'Setting' sheet: {new_data}")

        # Write the updated data back to the 'Setting' sheet
        response = service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=setting_sheet_range,
            body={'values': new_data},
            valueInputOption='USER_ENTERED'
        ).execute()

        # Log the response from the update request
        logging.info(f"Update response: {response}")
        return True

    except HttpError as error:
        logging.error(f"An error occurred while updating the Setting sheet for spreadsheet {spreadsheet_id}: {error}")
        raise

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

def monitor_and_update(service, display_sheet_log_id: str):
    state = load_state()
    while True:
        try:
            spreadsheet_ids = get_spreadsheet_ids(service, display_sheet_log_id)
            changes_made = False
            current_time = int(time.time())

            for spreadsheet_id in spreadsheet_ids:
                try:
                    last_check_time = state.get(spreadsheet_id, 0)
                    sheet_data = get_sheet_data(service, spreadsheet_id)
                    
                    if current_time - last_check_time > CHECK_INTERVAL:
                        if update_setting_sheet(service, spreadsheet_id, sheet_data):
                            changes_made = True
                            state[spreadsheet_id] = current_time
                except HttpError as error:
                    if error.resp.status == 429:
                        logging.warning(f"Rate limit exceeded for spreadsheet {spreadsheet_id}. Skipping to next spreadsheet.")
                    else:
                        logging.error(f"Error processing spreadsheet {spreadsheet_id}: {error}")
            
            if changes_made:
                logging.info("Changes detected and applied. Continuing monitoring...")
                save_state(state)
            else:
                logging.info("No changes detected. Continuing monitoring...")
            
            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            logging.error(f"An error occurred during monitoring: {str(e)}")
            logging.info("Retrying in 60 seconds...")
            time.sleep(60)

def sheet_checker():
    creds = get_credentials()
    service = build('sheets', 'v4', credentials=creds)

    display_sheet_log_id = os.getenv("DISPLAY_SHEET_LOG_ID")
    if not display_sheet_log_id:
        logging.error("DISPLAY_SHEET_LOG_ID not found in environment variables")
        return

    logging.info("Starting continuous monitoring of Google Sheets...")
    monitor_and_update(service, display_sheet_log_id)