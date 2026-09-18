import os
import json
import gspread
from google.oauth2.service_account import Credentials

print("--- INICIANDO DIAGNÓSTICO DEL BOT ---")

# 1. Verificar credenciales de Google
try:
    creds_json = os.environ.get("GCP_CREDENTIALS")
    if not creds_json:
        print("❌ ERROR: La variable GCP_CREDENTIALS está vacía en GitHub Secrets.")
    else:
        print("✔ GCP_CREDENTIALS detectada correctamente.")
        
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    print("✔ Autenticación con Google Cloud exitosa.")
except Exception as e:
    print(f"❌ Error al autenticar con Google: {e}")
# Reemplazar la sección de conexión a la planilla por esta:
try:
    creds_json = os.environ.get("GCP_CREDENTIALS", "").strip()
    spreadsheet_id = os.environ.get("SPREADSHEET_ID", "").strip()
    
    # Limpiar comillas extras si se pegaron por error en GitHub Secrets
    spreadsheet_id = spreadsheet_id.replace('"', '').replace("'", "")
    
    print(f"📌 Intentando conectar al ID: '{spreadsheet_id}'")
    
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    
    # Abrir la planilla directamente por su clave de ID
    spreadsheet = client.open_by_key(spreadsheet_id)
    sheet = spreadsheet.sheet1
    filas = sheet.get_all_records()
    print(f"✔ Planilla abierta con éxito. Filas detectadas: {len(filas)}")
except Exception as e:
    print(f"❌ Error al abrir la planilla: {e}")
    exit(1)
# 2. Verificar lectura de la Planilla
try:
    spreadsheet_id = os.environ.get("SPREADSHEET_ID")
    print(f"Buscando planilla con ID: {spreadsheet_id}")
    
    sheet = client.open_by_key(spreadsheet_id).sheet1
    filas = sheet.get_all_records()
    print(f"✔ Planilla abierta correctamente. Total de filas encontradas: {len(filas)}")
    
    if len(filas) == 0:
        print("⚠️ La planilla no tiene filas con datos o no leyó los encabezados.")
    else:
        print("Muestra de la primera fila obtenida:", filas[0])

except Exception as e:
    print(f"❌ Error al abrir la planilla: {e}")

print("--- FIN DEL DIAGNÓSTICO ---")
