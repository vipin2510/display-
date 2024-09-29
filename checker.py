import os
import logging
import time
import json
import httpx
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Vercel KV API URLs and tokens
VERCEL_KV_URL = os.getenv("display_REST_API_URL")
VERCEL_KV_TOKEN = os.getenv("display_REST_API_TOKEN")

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Define the scopes
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# Rate limiting constants
REQUESTS_PER_MINUTE = 50
SECONDS_PER_MINUTE = 60

# Monitoring constants
CHECK_INTERVAL = 45  # Check for changes every 45 seconds

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
def get_spreadsheet_ids(service, display_sheet_log_id: str):
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
def get_sheet_data(service, spreadsheet_id: str):
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
def update_setting_sheet(service, spreadsheet_id: str, sheet_data):
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

        existing_sheets = {row[0]: row for row in existing_data[1:] if len(row) >= 3}
        
        for sheet_name, columns in sheet_data.items():
            columns_string = ','.join(columns)
            if sheet_name in existing_sheets:
                existing_row = existing_sheets[sheet_name]
                existing_row[2] = columns_string
                new_data.append(existing_row)
            else:
                new_data.append([sheet_name, "10", columns_string, "", "last 5 row", "", ""])

        response = service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=setting_sheet_range,
            body={'values': new_data},
            valueInputOption='USER_ENTERED'
        ).execute()

        logging.info(f"Update response: {response}")
        return True

    except HttpError as error:
        logging.error(f"An error occurred while updating the Setting sheet for spreadsheet {spreadsheet_id}: {error}")
        raise

async def load_state():
    try:
        # Make a GET request to Vercel KV
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{VERCEL_KV_URL}/kv/sheet_state", headers={"Authorization": f"Bearer {VERCEL_KV_TOKEN}"})
            if response.status_code == 200:
                return json.loads(response.text)
            else:
                logging.error(f"Error fetching state from Vercel KV: {response.text}")
                return {}
    except Exception as e:
        logging.error(f"Error loading state from KV: {str(e)}")
        return {}

async def save_state(state):
    try:
        # Make a PUT request to Vercel KV
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{VERCEL_KV_URL}/kv/sheet_state",
                headers={"Authorization": f"Bearer {VERCEL_KV_TOKEN}"},
                json={"value": json.dumps(state)}
            )
            if response.status_code != 200:
                logging.error(f"Error saving state to Vercel KV: {response.text}")
    except Exception as e:
        logging.error(f"Error saving state to KV: {str(e)}")

async def monitor_and_update(service, display_sheet_log_id):
    state = await load_state()
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
                await save_state(state)
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