import os
import json
import re
from playwright.sync_api import sync_playwright
import gspread
from google.oauth2.service_account import Credentials

# 1. Autenticación con Google Sheets desde los Secrets
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds_json = os.environ.get("GCP_CREDENTIALS")
if not creds_json:
    raise ValueError("No se encontró la variable de entorno GCP_CREDENTIALS")

creds_dict = json.loads(creds_json)
credentials = Credentials.from_service_account_info(creds_dict, scopes=scope)
gc = gspread.authorize(credentials)

# Abrir la planilla existente
spreadsheet_id = os.environ.get("SPREADSHEET_ID")
sh = gc.open_by_key(spreadsheet_id).sheet1

def consultar_expediente_senado(page, expediente):
    """
    Simula la navegación en la web del Senado PBA y devuelve el estado actual.
    """
    try:
        # Parsear formato (ej: "E 3 2024-2025" o "E-3/24-25")
        partes = re.search(r'([a-zA-Z]+)\s*[\-\/]?\s*(\d+)\s*[\-\/]?\s*([\d\-]+)', str(expediente))
        if not partes:
            print(f"Formato no reconocido para: {expediente}")
            return None

        letra = partes.group(1).upper()
        numero = partes.group(2)
        anio = partes.group(3)

        if len(anio) == 5 and "-" in anio:
            a = anio.split("-")
            anio = f"20{a[0]}-20{a[1]}"

        # Ir a la web del Senado PBA
        page.goto("https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx", timeout=60000)
        
        # Seleccionar la pestaña "PROYECTOS"
        page.click("input[id*='btnProyectos'], button:has-text('PROYECTOS'), a:has-text('PROYECTOS')")
        page.wait_for_timeout(1000)

        # Completar los desplegables y campos
        page.select_option("select[id*='ddlLetraP']", value=letra)
        page.fill("input[id*='txtNumeroP']", numero)
        page.select_option("select[id*='ddlPeriodoP']", label=anio)

        # Hacer clic en el botón de Búsqueda real
        page.click("input[id*='btnBuscarP']")
        page.wait_for_timeout(3000)

        # Extraer el texto de la columna Estado en la tabla resultante
        if page.is_visible("table"):
            filas = page.query_selector_all("table tr")
            for fila in filas:
                texto = fila.inner_text()
                if "En Estudio" in texto or "Aprobado" in texto or "Comisión" in texto or "Media Sanción" in texto:
                    match = re.search(r'(En Estudio|Aprobado c\/Modificaciones|Aprobado|Archivado|Media Sanción|En Comisión|Sancionado|Promulgada)', texto, re.I)
                    if match:
                        return match.group(0)

        return "Sin cambios / No hallado"
    except Exception as e:
        print(f"Error consultando {expediente}: {e}")
        return None

def main():
    registros = sh.get_all_values()
    if not registros:
        print("La planilla está vacía.")
        return

    # Mapeo de columnas (0 = Columna A, 3 = Columna D, etc.)
    # Ajusta estos índices según tu planilla original
    COLUMNA_EXPEDIENTE = 0
    COLUMNA_ESTADO = 3
    COLUMNA_FECHA = 4

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        for idx, fila in enumerate(registros[1:], start=2): # Salta encabezados
            if len(fila) <= COLUMNA_EXPEDIENTE or not fila[COLUMNA_EXPEDIENTE]:
                continue

            expediente = fila[COLUMNA_EXPEDIENTE]
            estado_guardado = fila[COLUMNA_ESTADO] if len(fila) > COLUMNA_ESTADO else ""

            print(f"Procesando expediente: {expediente}...")
            nuevo_estado = consultar_expediente_senado(page, expediente)

            if nuevo_estado and nuevo_estado != estado_guardado:
                print(f"🚨 ¡CAMBIO DE ESTADO DETECTADO! {expediente}: '{estado_guardado}' -> '{nuevo_estado}'")
                # Actualizar celda en la planilla original
                sh.update_cell(idx, COLUMNA_ESTADO + 1, nuevo_estado)
                if COLUMNA_FECHA < len(fila):
                    from datetime import datetime
                    sh.update_cell(idx, COLUMNA_FECHA + 1, datetime.now().strftime("%Y-%m-%d %H:%M"))

        browser.close()

if __name__ == "__main__":
    main()
