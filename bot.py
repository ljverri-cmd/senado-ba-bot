import os
import re
import json
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

def autenticar_google_sheets():
    creds_raw = os.environ.get("GCP_CREDENTIALS")
    spreadsheet_id = os.environ.get("SPREADSHEET_ID")
    
    if not creds_raw or not spreadsheet_id:
        raise ValueError("Faltan configurar los Secrets GCP_CREDENTIALS o SPREADSHEET_ID en GitHub")

    # Limpiar posibles saltos de línea o comillas extraas al pegar el Secret
    creds_raw = creds_raw.strip()
    if creds_raw.startswith("'") and creds_raw.endswith("'"):
        creds_raw = creds_raw[1:-1]
    if creds_raw.startswith('"') and creds_raw.endswith('"'):
        creds_raw = creds_raw[1:-1]

    try:
        creds_dict = json.loads(creds_raw)
    except Exception as e:
        raise ValueError(f"El Secret GCP_CREDENTIALS no es un JSON válido: {e}")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(credentials)
    return gc.open_by_key(spreadsheet_id).sheet1
