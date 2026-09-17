import os
import re
import json
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

def autenticar_google_sheets():
    # Obtener el JSON guardado en los Secrets de GitHub
    creds_json = os.environ.get("GCP_CREDENTIALS")
    spreadsheet_id = os.environ.get("SPREADSHEET_ID")
    
    if not creds_json or not spreadsheet_id:
        raise ValueError("Faltan configurar los Secrets GCP_CREDENTIALS o SPREADSHEET_ID en GitHub")

    # Definir los permisos requeridos para Google Sheets y Drive
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    # Cargar las credenciales directamente desde la variable de entorno
    creds_dict = json.loads(creds_json)
    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    
    # Conectar mediante gspread
    gc = gspread.authorize(credentials)
    return gc.open_by_key(spreadsheet_id).sheet1

def consultar_estado_senado(page, expediente):
    match = re.search(r'([a-zA-Z]+)\s*[\-\/]?\s*(\d+)\s*[\-\/]?\s*([\d\-]+)', str(expediente))
    if not match:
        return None

    letra = match.group(1).upper()
    numero = match.group(2)
    periodo_raw = match.group(3)

    if "-" in periodo_raw and len(periodo_raw) == 5:
        p1, p2 = periodo_raw.split("-")
        periodo = f"20{p1}-20{p2}"
    else:
        periodo = periodo_raw

    url = "https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx"
    page.goto(url, wait_until="networkidle")

    page.click("text=PROYECTOS")
    page.wait_for_timeout(1000)

    page.select_option("select[id*='ddlLetraP']", value=letra)
    page.fill("input[id*='txtNumeroP']", numero)
    page.select_option("select[id*='ddlPeriodoP']", label=periodo)

    page.click("input[id*='btnBuscarP']")
    page.wait_for_timeout(3000)

    try:
        estado_elem = page.locator("span[id*='lblEstado'], td.estado, .table-responsive td:nth-child(4)").first
        if estado_elem.is_visible():
            return estado_elem.inner_text().strip()
    except Exception:
        pass

    return None

def main():
    print("Iniciando monitoreo del Senado PBA...")
    hoja = autenticar_google_sheets()
    filas = hoja.get_all_records()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for idx, fila in enumerate(filas, start=2):
            expediente = fila.get("EXPEDIENTE LEGISLATIVO") or fila.get("Expediente")
            estado_actual = fila.get("ESTADO EN COMISIÓN CÁMARA DE ORIGEN") or fila.get("Estado Guardado")

            if not expediente:
                continue

            print(f"Consultando expediente: {expediente}...")
            nuevo_estado = consultar_estado_senado(page, expediente)

            if nuevo_estado and nuevo_estado != estado_actual:
                print(f"🚨 ¡CAMBIO DETECTADO! {expediente}: '{estado_actual}' -> '{nuevo_estado}'")
                hoja.update_cell(idx, 6, nuevo_estado)
            else:
                print(f"Sin cambios para {expediente}.")

        browser.close()

if __name__ == "__main__":
    main()
