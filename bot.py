import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials

print("--- INICIANDO DIAGNÓSTICO DEL BOT ---")

# 1. Verificar credenciales de Google
try:
    creds_json = os.environ.get("GCP_CREDENTIALS")
    if not creds_json:
        print("❌ ERROR: La variable GCP_CREDENTIALS está vacía en GitHub Secrets.")
    else:
        print("✔ GCP_CREDENTIALS detectada correctamente.")
        
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(creds_json)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    print("✔ Autenticación con Google Cloud exitosa.")
except Exception as e:
    print(f"❌ Error al autenticar con Google: {e}")

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
