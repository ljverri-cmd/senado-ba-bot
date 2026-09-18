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

# 2. Función de Scraping corregida para Playwright
def consultar_estado_senado(page, expediente):
    exp_str = str(expediente).strip()
    match = re.search(r'([a-zA-Z]+)\s*[\-\/]?\s*(\d+)\s*[\-\/]?\s*([\d\-]+)', exp_str)
    
    if not match:
        print(f"⚠️ No se pudo interpretar el expediente: '{exp_str}'")
        return None

    letra = match.group(1).upper()
    numero = match.group(2)
    periodo_raw = match.group(3)

    if "-" in periodo_raw and len(periodo_raw) == 5:
        p1, p2 = periodo_raw.split("-")
        periodo = f"20{p1}-20{p2}"
    else:
        periodo = periodo_raw

    print(f"   🔎 Buscando -> Letra: '{letra}', Número: '{numero}', Período: '{periodo}'")

    try:
        # Cargar el sitio principal
        page.goto("https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx", wait_until="domcontentloaded", timeout=60000)
        
        # PASO CLAVE CORREGIDO: Hacer clic en la pestaña "Proyectos" usando locators estándar
        tab_proyectos = page.get_by_role("link", name="PROYECTOS").or_(page.locator("a:has-text('PROYECTOS'), [id*='btnProyectos']")).first
        if tab_proyectos.is_visible(timeout=5000):
            tab_proyectos.click()
            page.wait_for_timeout(1500)

        # Esperar a que aparezcan los desplegables
        select_letra = page.locator("select").first
        select_letra.wait_for(state="visible", timeout=20000)

        # Seleccionar Tipo/Letra (E, D, F, etc.)
        try:
            select_letra.select_option(value=letra)
        except Exception:
            select_letra.select_option(label=letra)

        # Completar Número de expediente
        input_num = page.locator("input[type='text']").first
        input_num.fill(numero)

        # Seleccionar Período (segundo desplegable)
        selects = page.locator("select").all()
        if len(selects) > 1:
            try:
                selects[1].select_option(label=periodo)
            except Exception:
                selects[1].select_option(value=periodo)

        # Clic en el botón Buscar
        btn_buscar = page.locator("input[type='submit'], button, input[value*='Buscar']").first
        btn_buscar.click()

        # Esperar la recarga de resultados
        page.wait_for_timeout(3500)

        html_respuesta = page.content()

        # Regex para capturar el estado resultante
        patron = r'(En Estudio|Aprobado c\/Modificaciones|Aprobado|Archivado|Media Sanción|En Comisión|Sancionado|Promulgada)'
        match_estado = re.search(patron, html_respuesta, re.IGNORECASE)

        if match_estado:
            return match_estado.group(0).strip()
        
        print("   ⚠️ No se encontró estado visible en los resultados.")
        return None

    except Exception as err:
        print(f"   ❌ Error durante la consulta: {err}")
        return None

# 3. Procesamiento de filas
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    page = context.new_page()

    for idx, fila in enumerate(filas, start=2):
        expediente = None
        estado_guardado = None

        # Detectar columnas automáticamente
        for clave, valor in fila.items():
            clave_lower = str(clave).lower().strip()
            if "expediente" in clave_lower:
                expediente = valor
            elif "estado" in clave_lower:
                estado_guardado = valor

        if not expediente:
            continue

        print(f"\n📌 Fila {idx} | Expediente: '{expediente}' | Estado en Sheet: '{estado_guardado}'")
        
        estado_web = consultar_estado_senado(page, expediente)

        if estado_web:
            print(f"   🌐 Estado en web: '{estado_web}'")
            if str(estado_web).strip().lower() != str(estado_guardado).strip().lower():
                print(f"   🚨 ¡CAMBIO DETECTADO! Actualizando fila {idx}...")
                
                # Reemplaza '6' por la posición numérica real de la columna del Estado en tu planilla (A=1, B=2, C=3, D=4, E=5, F=6, etc.)
                sheet.update_cell(idx, 6, estado_web)
                print("   ✔ Fila actualizada en Google Sheets.")
            else:
                print("   ℹ️ Sin cambios.")
        else:
            print("   ⚠️ No se actualizó la fila.")

    browser.close()

print("\n--- 🏁 PROCESO FINALIZADO ---")
