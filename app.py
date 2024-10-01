from flask import Flask, render_template, request, jsonify, make_response, redirect, url_for, send_file, send_from_directory
from datetime import datetime
import os
import io
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import logging

logging.basicConfig(level=logging.INFO)

# Check if we're running on Vercel
ON_VERCEL = os.environ.get('VERCEL')

# Load .env file if not on Vercel
if not ON_VERCEL:
    from dotenv import load_dotenv
    load_dotenv()

# Set up credentials using environment variables
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
credentials = {
    "type": os.environ.get("GOOGLE_SERVICE_ACCOUNT_TYPE"),
    "project_id": os.environ.get("GOOGLE_PROJECT_ID"),
    "private_key_id": os.environ.get("GOOGLE_PRIVATE_KEY_ID"),
    "private_key": os.environ.get("GOOGLE_PRIVATE_KEY").replace('\\n', '\n') if os.environ.get("GOOGLE_PRIVATE_KEY") else None,
    "client_email": os.environ.get("GOOGLE_CLIENT_EMAIL"),
    "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
    "auth_uri": os.environ.get("GOOGLE_AUTH_URI"),
    "token_uri": os.environ.get("GOOGLE_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.environ.get("GOOGLE_AUTH_PROVIDER_X509_CERT_URL"),
    "client_x509_cert_url": os.environ.get("GOOGLE_CLIENT_X509_CERT_URL")
}

creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials, scope)
client = gspread.authorize(creds)
drive_service = build('drive', 'v3', credentials=creds)

app = Flask(__name__)
app.secret_key = os.urandom(24)

TEMPLATE_SPREADSHEET_ID = '19SKGC7kUFi3ZVZEHxSavCrGOMuHVQASs-3jTIddFedg'
DB_SHEET_THANA_ID = os.environ.get('DB_SHEET_THANA_ID')

@app.route('/assets/css/<path:filename>')
def css(filename):
    return send_from_directory('assets/css', filename)

@app.route('/assets/icons/<path:filename>')
def icons(filename):
    return send_from_directory('assets/icons', filename)

def setup_db_sheet_thana():
    global DB_SHEET_THANA_ID
    try:
        if DB_SHEET_THANA_ID:
            spreadsheet = client.open_by_key(DB_SHEET_THANA_ID)
            logging.info(f"Using existing db_sheet_thana with ID: {DB_SHEET_THANA_ID}")
        else:
            spreadsheet = client.create("db_sheet_thana")
            DB_SHEET_THANA_ID = spreadsheet.id
            sheet = spreadsheet.sheet1
            sheet.update_title("Thana Spreadsheets")
            headers = ["Thana Name", "Email", "Created Time", "Spreadsheet ID"]
            sheet.insert_row(headers, 1)
            sheet.format('A1:D1', {
                "backgroundColor": {
                    "red": 0.9,
                    "green": 0.9,
                    "blue": 0.9
                },
                "horizontalAlignment": "CENTER",
                "textFormat": {
                    "bold": True
                }
            })
            logging.info(f"db_sheet_thana created successfully. Spreadsheet ID: {DB_SHEET_THANA_ID}")
        return DB_SHEET_THANA_ID
    except Exception as e:
        logging.error(f"Error setting up db_sheet_thana: {str(e)}")
        return None

def add_to_db_sheet_thana(thana_name, user_email, spreadsheet_id):
    try:
        sheet = client.open_by_key(DB_SHEET_THANA_ID).sheet1
        created_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_row = [thana_name, user_email, created_time, spreadsheet_id]
        sheet.append_row(new_row)
        logging.info(f"Added new entry to db_sheet_thana for {thana_name}: {new_row}")
    except Exception as e:
        logging.error(f"Error adding to db_sheet_thana: {str(e)}")
        raise

def create_user_spreadsheet(thana_name, user_email):
    try:
        copied_spreadsheet = drive_service.files().copy(
            fileId=TEMPLATE_SPREADSHEET_ID,
            body={'name': f"{thana_name} Spreadsheet"}
        ).execute()
        spreadsheet_id = copied_spreadsheet['id']

        # Make the spreadsheet publicly accessible
        drive_service.permissions().create(
            fileId=spreadsheet_id,
            body={'type': 'anyone', 'role': 'writer'},
            fields='id'
        ).execute()

        add_to_db_sheet_thana(thana_name, user_email, spreadsheet_id)
        logging.info(f"Created new public spreadsheet for {thana_name} with ID: {spreadsheet_id}")
        return spreadsheet_id
    except Exception as e:
        logging.error(f"Error creating public user spreadsheet: {str(e)}")
        raise

def get_existing_thana_spreadsheet(thana_name):
    try:
        sheet = client.open_by_key(DB_SHEET_THANA_ID).sheet1
        all_data = sheet.get_all_values()
        for row in all_data[1:]:  # Skip header row
            if row[0].lower() == thana_name.lower():
                return row[3]  # Return the spreadsheet ID
        return None
    except Exception as e:
        logging.error(f"Error fetching existing thana spreadsheet: {str(e)}")
        return None

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'new_thana':
            thana_name = request.form.get('thana_name')
            user_email = request.form.get('user_email')
            
            if not thana_name or not user_email:
                return render_template('index.html', error="Please provide both Thana name and email.")
            
            try:
                spreadsheet_id = create_user_spreadsheet(thana_name, user_email)
                message = f"Sheet created for {thana_name} on {user_email}. "
                message += f'<a href="{url_for("existing_thana")}">Go to existing sheet</a>'
                return render_template('index.html', message=message)
            except Exception as e:
                logging.error(f"Error in index route: {str(e)}")
                return render_template('index.html', error="An error occurred while creating the spreadsheet. Please try again.")
        
        elif action == 'existing_thana':
            return redirect(url_for('existing_thana'))
    
    return render_template('index.html')

@app.route('/existing_thana', methods=['GET', 'POST'])
def existing_thana():
    if request.method == 'POST':
        thana_name = request.form.get('thana_name')
        spreadsheet_id = get_existing_thana_spreadsheet(thana_name)
        
        if not spreadsheet_id:
            return render_template('existing_thana.html', error="Thana not found. Please check the name and try again.")
        
        return redirect(url_for('display_sheet', spreadsheet_id=spreadsheet_id))
    
    return render_template('existing_thana.html')

@app.route('/sheet/<spreadsheet_id>', methods=['GET'])
def display_sheet(spreadsheet_id):
    try:
        settings = get_settings(spreadsheet_id)
        sheets_data = []
        for setting in settings:
            headers, data = get_sheet_data(
                setting['sheet_name'],
                setting['columns_to_display'],
                setting['photo_column'],
                setting['display'],
                spreadsheet_id
            )
            sheets_data.append({
                'title': setting['title'],
                'headers': headers,
                'data': data,
                'time_of_display': setting['time_of_display']
            })
        
        spreadsheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        
        return render_template('sheet.html', sheets_data=sheets_data, spreadsheet_url=spreadsheet_url)
    except Exception as e:
        app.logger.error(f"An error occurred: {str(e)}")
        return f"An error occurred: {str(e)}"

def get_settings(spreadsheet_id):
    sheet = client.open_by_key(spreadsheet_id).worksheet('Setting')
    settings = sheet.get_all_values()[1:]  # Exclude header row
    return [
        {
            'sheet_name': row[0],
            'time_of_display': int(row[1]),
            'columns_to_display': row[3].split(','),  # D: Columns to display
            'photo_column': row[6] if row[6] else None,  # G: Image column
            'display': row[4],
            'title': row[2]
        }
        for row in settings
    ]

def get_sheet_data(sheet_name, columns_to_display, photo_column, display, spreadsheet_id):
    if display != "yes":
        return [], []
    
    sheet = client.open_by_key(spreadsheet_id).worksheet(sheet_name)
    all_data = sheet.get_all_values()
    headers = all_data[0]
    
    selected_data = []
    for row in all_data[1:]:
        row_data = []
        for col in columns_to_display:
            try:
                col_index = headers.index(col.strip())  # Find the column index from headers
                row_data.append(row[col_index])
            except ValueError:
                row_data.append(f"Column {col} not found")
        if photo_column:
            try:
                photo_col_index = headers.index(photo_column)
                row_data.append(f'<img src="{row[photo_col_index]}" alt="Photo" width="100" height="100">')
            except ValueError:
                row_data.append(f"Photo column {photo_column} not found")
        selected_data.append(row_data)
    
    return headers, selected_data

if __name__ == '__main__':
    if ON_VERCEL:
        app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
    else:
        app.run(debug=True)
