import os
import json
import re
import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

print("--- 🚀 INICIANDO BOT DE MONITOREO SENADO PBA ---")

# 1. Autenticación y lectura de Google Sheets
try:
    creds_json = os.environ.get("GCP_CREDENTIALS", "").strip()
    spreadsheet_id = os.environ.get("SPREADSHEET_ID", "").strip().replace('"', '').replace("'", "")

    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)

    sheet = client.open_by_key(spreadsheet_id).sheet1
    filas = sheet.get_all_records()
    print(f"✔ Planilla abierta correctamente. Se leyeron {len(filas)} filas.")
except Exception as e:
    print(f"❌ Error al abrir Google Sheets: {e}")
    exit(1)

# 2. Función de consulta HTTP directa
def consultar_estado_senado(expediente):
    exp_str = str(expediente).strip()
    match = re.search(r'([a-zA-Z]+)\s*[\-\/]?\s*(\d+)\s*[\-\/]?\s*([\d\-]+)', exp_str)
    
    if not match:
        print(f"⚠️ Formato no válido de expediente: '{exp_str}'")
        return None

    letra = match.group(1).upper()
    numero = match.group(2)
    periodo_raw = match.group(3)

    if "-" in periodo_raw and len(periodo_raw) == 5:
        p1, p2 = periodo_raw.split("-")
        periodo = f"20{p1}-20{p2}"
    else:
        periodo = periodo_raw

    print(f"   🔎 Consultando -> Letra: '{letra}', Número: '{numero}', Período: '{periodo}'")

    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    url_base = "https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx"

    try:
        # Obtener ViewState de ASP.NET
        resp_get = session.get(url_base, headers=headers, timeout=30)
        soup_get = BeautifulSoup(resp_get.text, 'html.parser')

        viewstate = soup_get.find("input", {"id": "__VIEWSTATE"})
        eventvalidation = soup_get.find("input", {"id": "__EVENTVALIDATION"})

        payload = {
            "__VIEWSTATE": viewstate["value"] if viewstate else "",
            "__EVENTVALIDATION": eventvalidation["value"] if eventvalidation else "",
            "ctl00$ContentPlaceHolder1$ddlTipoP": letra,
            "ctl00$ContentPlaceHolder1$txtNumeroP": numero,
            "ctl00$ContentPlaceHolder1$ddlPeriodoP": periodo,
            "ctl00$ContentPlaceHolder1$btnBuscarP": "Buscar"
        }

        # Enviar petición POST
        resp_post = session.post(url_base, data=payload, headers=headers, timeout=30)
        
        # Parsear resultados
        patron = r'(En Estudio|Aprobado c\/Modificaciones|Aprobado|Archivado|Media Sanción|En Comisión|Sancionado|Promulgada)'
        match_estado = re.search(patron, resp_post.text, re.IGNORECASE)

        if match_estado:
            return match_estado.group(0).strip()

        return "Sin cambios / En Estudio"

    except Exception as err:
        print(f"   ❌ Error en la solicitud HTTP: {err}")
        return None

# 3. Procesamiento de filas
for idx, fila in enumerate(filas, start=2):
    expediente = None
    estado_guardado = None

    for clave, valor in fila.items():
        clave_lower = str(clave).lower().strip()
        if "expediente" in clave_lower:
            expediente = valor
        elif "estado" in clave_lower:
            estado_guardado = valor

    if not expediente:
        continue

    print(f"\n📌 Fila {idx} | Expediente: '{expediente}' | Estado en Sheet: '{estado_guardado}'")
    
    estado_web = consultar_estado_senado(expediente)

    if estado_web:
        print(f"   🌐 Estado en web: '{estado_web}'")
        if str(estado_web).strip().lower() != str(estado_guardado).strip().lower():
            print(f"   🚨 ¡CAMBIO DETECTADO! Actualizando fila {idx}...")
            # Columna '6' (o la columna numérica asignada al estado)
            sheet.update_cell(idx, 6, estado_web)
            print("   ✔ Fila actualizada en Google Sheets.")
        else:
            print("   ℹ️ Sin cambios.")

print("\n--- 🏁 PROCESO FINALIZADO ---")
