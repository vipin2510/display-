from flask import Flask, render_template, request, jsonify, make_response, redirect, url_for, send_file
from datetime import datetime, timedelta
import os
import io
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import json
import uuid
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

# TEMPLATE_SPREADSHEET_ID = '1PUDas9d9cbRW-rxZTaaTPj_je_A_ELo8-dqTMjz8qMY'
TEMPLATE_SPREADSHEET_ID = '19SKGC7kUFi3ZVZEHxSavCrGOMuHVQASs-3jTIddFedg'
DB_SHEET_THANA_ID = os.environ.get('DB_SHEET_THANA_ID')

def setup_db_sheet_thana():
    global DB_SHEET_THANA_ID
    try:
        if DB_SHEET_THANA_ID:
            # Try to open the existing spreadsheet
            spreadsheet = client.open_by_key(DB_SHEET_THANA_ID)
            logging.info(f"Using existing db_sheet_thana with ID: {DB_SHEET_THANA_ID}")
        else:
            # Create a new spreadsheet if ID is not provided
            spreadsheet = client.create("db_sheet_thana")
            DB_SHEET_THANA_ID = spreadsheet.id
            
            # Get the first sheet
            sheet = spreadsheet.sheet1
            
            # Rename the sheet
            sheet.update_title("Thana Spreadsheets")
            
            # Set up the headers
            headers = ["Thana Name", "Email", "Created Time", "Spreadsheet ID"]
            sheet.insert_row(headers, 1)
            
            # Format the header row
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
        raise  # Re-raise the exception to be caught in the calling function


def create_user_spreadsheet(thana_name, user_email):
    try:
        # Copy the entire spreadsheet
        copied_spreadsheet = drive_service.files().copy(
            fileId=TEMPLATE_SPREADSHEET_ID,
            body={'name': f"{thana_name} Spreadsheet"}
        ).execute()
        spreadsheet_id = copied_spreadsheet['id']

        # Share the copied spreadsheet with the user
        drive_service.permissions().create(
            fileId=spreadsheet_id,
            body={'type': 'user', 'role': 'writer', 'emailAddress': user_email},
            fields='id'
        ).execute()

        # Add the new spreadsheet to db_sheet_thana
        add_to_db_sheet_thana(thana_name, user_email, spreadsheet_id)

        logging.info(f"Created new spreadsheet for {thana_name} with ID: {spreadsheet_id}")
        return spreadsheet_id
    except Exception as e:
        logging.error(f"Error creating user spreadsheet: {str(e)}")
        raise  # Re-raise the exception to be caught in the route handler


def get_all_sheets_data(spreadsheet_id, selected_date):
    # Open the spreadsheet
    spreadsheet = client.open_by_key(spreadsheet_id)
    all_data = []
    headers_set = False
    headers = []

    selected_date_obj = datetime.strptime(selected_date, "%Y-%m-%d")

    # Iterate through all sheets in the spreadsheet
    for sheet in spreadsheet.worksheets():
        rows = sheet.get_all_values()
        
        if not headers_set:
            headers = ['क्रमांक'] + rows[0][1:5]  # Set headers only once, exclude the first and last columns
            headers_set = True

        for row in rows[1:]:
            try:
                row_date = datetime.strptime(row[-1], "%m/%d/%Y")
                if row_date.date() == selected_date_obj.date():
                    all_data.append(row[1:5])  # Exclude the first and last columns
            except ValueError:
                app.logger.warning(f"Invalid date format in row: {row}")
                continue  # Skip rows with invalid date format
    print(spreadsheet.worksheets())
    return headers, all_data

def get_file_id_from_url(url):
    file_id = None
    if 'drive.google.com' in url:
        if '/file/d/' in url:
            file_id = url.split('/file/d/')[1].split('/')[0]
        elif 'id=' in url:
            file_id = url.split('id=')[1].split('&')[0]
    return file_id

@app.route('/get_image/<file_id>')
def get_image(file_id):
    try:
        # Use the Google Drive API to download the image
        request = drive_service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()

        fh.seek(0)
        return send_file(fh, mimetype='image/jpeg', as_attachment=False)
    except Exception as e:
        app.logger.error(f"Error fetching image: {str(e)}")
        return redirect('/static/placeholder.png')

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
            'title': row[5]
        }
        for row in settings if row[1] != '0'  # Exclude rows with time_of_display = 0
    ]

def get_sheet_data(sheet_name, columns_to_display, photo_column, display_type, spreadsheet_id):
    sheet = client.open_by_key(spreadsheet_id).worksheet(sheet_name)
    all_values = sheet.get_all_values()
    headers = [all_values[0][ord(col) - ord('A')] for col in columns_to_display]
    data = []
    for row in all_values[1:]:
        row_data = []
        for col in columns_to_display:
            cell_value = row[ord(col) - ord('A')]
            # Check if the column is the photo column
            if col == photo_column:
                file_id = get_file_id_from_url(cell_value)
                if file_id:
                    # Link to download the image via Flask route
                    cell_value = f'/get_image/{file_id}'
            row_data.append(cell_value)
        data.append(row_data)
    if display_type == 'last 5 row':
        data = data[-5:]
    
    return headers, data

@app.route('/', methods=['GET', 'POST'])
def index():
    user_id = request.cookies.get('user_id')
    spreadsheet_id = request.cookies.get('spreadsheet_id')

    if user_id and spreadsheet_id:
        return redirect(url_for('display_sheet'))

    if request.method == 'POST':
        thana_name = request.form.get('thana_name')
        user_email = request.form.get('user_email')

        if not thana_name or not user_email:
            return render_template('index.html', error="Please provide both Thana name and email.")

        try:
            spreadsheet_id = create_user_spreadsheet(thana_name, user_email)
            user_id = str(uuid.uuid4())

            response = make_response(redirect(url_for('display_sheet')))
            response.set_cookie('user_id', user_id, max_age=30*24*60*60)  # 30 days expiration
            response.set_cookie('spreadsheet_id', spreadsheet_id, max_age=30*24*60*60)
            return response
        except Exception as e:
            logging.error(f"Error in index route: {str(e)}")
            return render_template('index.html', error="An error occurred while creating the spreadsheet. Please try again.")

    return render_template('index.html')

@app.route('/sheet', methods=['GET', 'POST'])
def display_sheet():
    user_id = request.cookies.get('user_id')
    spreadsheet_id = request.cookies.get('spreadsheet_id')

    if not user_id or not spreadsheet_id:
        return redirect(url_for('index'))

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
        
        # Generate the spreadsheet URL
        spreadsheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        
        return render_template('sheet.html', sheets_data=sheets_data, spreadsheet_url=spreadsheet_url)
    except Exception as e:
        app.logger.error(f"An error occurred: {str(e)}")
        return f"An error occurred: {str(e)}"

@app.route('/logout', methods=['POST'])
def logout():
    response = make_response(redirect(url_for('index')))
    response.delete_cookie('user_id')
    response.delete_cookie('spreadsheet_id')
    return response


@app.route('/check_changes', methods=['POST'])
def check_changes():
    try:
        spreadsheet_id = request.cookies.get('spreadsheet_id')
        if not spreadsheet_id:
            return jsonify({"error": "User not authenticated"}), 401

        selected_date = request.json.get('selected_date', datetime.now().strftime("%Y-%m-%d"))
        sheet = client.open_by_key(spreadsheet_id).worksheet('Sheet1')
        current_modified_time = sheet.updated

        headers, filtered_data = get_all_sheets_data(spreadsheet_id, selected_date)
        fetch_time = datetime.now().strftime("%H:%M:%S")

        return jsonify({
            "hasChanges": True,
            "html": render_template('sheet_content.html', headers=headers, data=filtered_data),
            "fetch_time": fetch_time
        })
    except Exception as e:
        app.logger.error(f"An error occurred in check_changes: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    db_sheet_id = setup_db_sheet_thana()
    if db_sheet_id:
        app.run(debug=True)
    else:
        logging.error("Failed to set up db_sheet_thana. Application not started.")
