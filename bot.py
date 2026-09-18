import os
import json
import re
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

print("--- 🚀 INICIANDO BOT DE MONITOREO SENADO PBA ---")

# 1. Autenticación y lectura de la planilla
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

# 2. Función de Scraping del Senado PBA con Playwright
def consultar_estado_senado(page, expediente):
    # Interpretar combinaciones como "E-3/24-25", "E 3 2024-2025" o "D-105/24-25"
    exp_str = str(expediente).strip()
    match = re.search(r'([a-zA-Z]+)\s*[\-\/]?\s*(\d+)\s*[\-\/]?\s*([\d\-]+)', exp_str)
    
    if not match:
        print(f"⚠️ No se pudo parsear el formato del expediente: '{exp_str}'")
        return None

    letra = match.group(1).upper()
    numero = match.group(2)
    periodo_raw = match.group(3)

    # Normalizar período (ej: "24-25" -> "2024-2025")
    if "-" in periodo_raw and len(periodo_raw) == 5:
        p1, p2 = periodo_raw.split("-")
        periodo = f"20{p1}-20{p2}"
    else:
        periodo = periodo_raw

    print(f"   🔎 Enviando al Senado -> Letra: '{letra}', Número: '{numero}', Período: '{periodo}'")

    try:
        page.goto("https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx", wait_until="networkidle", timeout=30000)
        
        # Seleccionar la pestaña "PROYECTOS"
        page.click("text=PROYECTOS")
        page.wait_for_timeout(1000)

        # Llenar el formulario de consulta
        page.select_option("select[id*='ddlLetra']", value=letra)
        page.fill("input[id*='txtNumero']", numero)
        
        # Intentar seleccionar el período por texto visible
        try:
            page.select_option("select[id*='ddlPeriodo']", label=periodo)
        except Exception:
            # Si falla por etiqueta, intenta por valor directo
            page.select_option("select[id*='ddlPeriodo']", value=periodo)

        # Hacer clic en el botón de búsqueda
        page.click("input[id*='btnBuscar']")
        page.wait_for_timeout(3000)

        # Capturar el contenido de la página tras la búsqueda
        html_respuesta = page.content()

        # Buscar estados comunes en el HTML devuelto
        patrón = r'(En Estudio|Aprobado c\/Modificaciones|Aprobado|Archivado|Media Sanción|En Comisión|Sancionado|Promulgada)'
        match_estado = re.search(patrón, html_respuesta, re.IGNORECASE)

        if match_estado:
            return match_estado.group(0).strip()
        
        print("   ⚠️ La página respondió pero no se encontró un texto de estado claro.")
        return None

    except Exception as err:
        print(f"   ❌ Error durante la navegación web: {err}")
        return None

# 3. Procesamiento de filas
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    for idx, fila in enumerate(filas, start=2): # Comienza en 2 omitiendo los encabezados
        # Buscar el nombre de la columna sin importar si variaron las mayúsculas/minúsculas
        expediente = None
        estado_guardado = None

        for clave, valor in fila.items():
            clave_lower = str(clave).lower().strip()
            if "expediente" in clave_lower:
                expediente = valor
            elif "estado" in clave_lower:
                estado_guardado = valor

        if not expediente:
            print(f"⏩ Fila {idx}: Columna de expediente vacía o no detectada.")
            continue

        print(f"\n📌 Fila {idx} | Expediente: '{expediente}' | Estado actual en Sheet: '{estado_guardado}'")
        
        estado_web = consultar_estado_senado(page, expediente)

        if estado_web:
            print(f"   🌐 Estado hallado en la web: '{estado_web}'")
            if str(estado_web).strip().lower() != str(estado_guardado).strip().lower():
                print(f"   🚨 ¡DIFERENCIA DETECTADA! Actualizando fila {idx} en Google Sheets...")
                
                # Asume que el estado va en la Columna D (4). Ajusta el '4' si tu estado está en otra columna.
                sheet.update_cell(idx, 4, estado_web)
                print("   ✔ Fila actualizada exitosamente.")
            else:
                print("   ℹ️ El estado coincide con el de la planilla. Sin cambios.")
        else:
            print("   ⚠️ No se pudo obtener la información desde la web.")

    browser.close()

print("\n--- 🏁 PROCESO FINALIZADO ---")
