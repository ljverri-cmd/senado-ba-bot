import os
import json
import re
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

print("--- 🚀 INICIANDO BOT CON SELECTORES EXACTOS SENADO PBA ---")

# 1. Autenticación en Google Sheets
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

    sh = client.open_by_key(spreadsheet_id)
    
    try:
        sheet_consolidado = sh.worksheet("Senado_PBA_Consolidado")
    except gspread.exceptions.WorksheetNotFound:
        sheet_consolidado = sh.add_worksheet(title="Senado_PBA_Consolidado", rows="1000", cols="10")

    print(f"✔ Conectado exitosamente a la planilla: '{sh.title}'")
except Exception as e:
    print(f"❌ Error al conectar con Google Sheets: {e}")
    exit(1)

ENCABEZADOS = [
    "EXPEDIENTE LEGISLATIVO",
    "OBJETO / CARÁTULA",
    "AUTOR DEL PROYECTO",
    "BLOQUE",
    "COMISIONES ASIGNADAS CÁMARA ORIGEN",
    "ESTADO EN COMISIÓN CÁMARA ORIGEN",
    "COMISIONES ASIGNADAS CÁMARA REVISORA",
    "ESTADO EN COMISIÓN CÁMARA REVISORA",
    "MEDIA SANCIÓN",
    "FECHA Y HORA ACTUALIZACIÓN"
]

if not sheet_consolidado.row_values(1):
    sheet_consolidado.append_row(ENCABEZADOS)

# 2. Scraping especializado utilizando los IDs nativos de ASP.NET
def extraer_datos_expediente(page, expediente):
    exp_str = str(expediente).strip()
    match = re.search(r'([a-zA-Z]+)\s*[\-\/]?\s*(\d+)\s*[\-\/]?\s*([\d\-]+)', exp_str)
    
    if not match:
        print(f"⚠️ Formato de expediente no válido: '{exp_str}'")
        return None

    letra = match.group(1).upper()
    numero = match.group(2)
    periodo_raw = match.group(3)

    if "-" in periodo_raw and len(periodo_raw) == 5:
        p1, p2 = periodo_raw.split("-")
        periodo = f"20{p1}-20{p2}"
    else:
        periodo = periodo_raw

    print(f"\n🔎 Consultando expediente: {exp_str} -> Tipo: '{letra}', Nro: '{numero}', Período: '{periodo}'")

    try:
        page.goto("https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1000)

        # Activar el panel de proyectos mediante __doPostBack o clic directo en el Tab
        try:
            page.evaluate("__doPostBack('ctl00$ContentPlaceHolder1$btnProyectos','')")
        except Exception:
            page.locator("a[id*='btnProyectos'], input[id*='btnProyectos']").first.click()

        page.wait_for_timeout(2000)

        # Identificadores precisos de los controles ASP.NET del formulario Proyectos
        id_tipo = "select[name*='ddlTipoP'], select[id*='ddlTipoP']"
        id_numero = "input[name*='txtNumeroP'], input[id*='txtNumeroP']"
        id_periodo = "select[name*='ddlPeriodoP'], select[id*='ddlPeriodoP']"
        id_buscar = "input[name*='btnBuscarP'], input[id*='btnBuscarP'], button[id*='btnBuscarP']"

        # Esperar a que el selector de tipo de proyecto sea visible en el DOM
        page.wait_for_selector(id_tipo, state="visible", timeout=15000)

        # Seleccionar Tipo / Letra (Ej: E, D, F)
        page.locator(id_tipo).first.select_option(value=letra)

        # Cargar Número
        page.locator(id_numero).first.fill(numero)

        # Seleccionar Período
        try:
            page.locator(id_periodo).first.select_option(label=periodo)
        except Exception:
            page.locator(id_periodo).first.select_option(value=periodo)

        # Disparar búsqueda
        page.locator(id_buscar).first.click()

        # Esperar a que la tabla AJAX procese los resultados
        page.wait_for_timeout(4000)

        html_page = page.content()

        if "No se encontraron registros" in html_page or "Sin resultados" in html_page:
            print("   ⚠️ No se encontraron resultados para este expediente.")
            return None

        # Extracción de los valores de las etiquetas devueltas
        objeto = page.locator("[id*='lblSumario'], [id*='lblObjeto']").first.text_content() if page.locator("[id*='lblSumario'], [id*='lblObjeto']").count() > 0 else "Sin datos"
        autor = page.locator("[id*='lblAutor']").first.text_content() if page.locator("[id*='lblAutor']").count() > 0 else "Sin datos"
        bloque = page.locator("[id*='lblBloque']").first.text_content() if page.locator("[id*='lblBloque']").count() > 0 else "Sin datos"
        
        com_origen = page.locator("[id*='lblComisionesOrigen']").first.text_content() if page.locator("[id*='lblComisionesOrigen']").count() > 0 else "Sin asignación"
        est_origen = page.locator("[id*='lblEstadoOrigen'], [id*='lblEstado']").first.text_content() if page.locator("[id*='lblEstadoOrigen'], [id*='lblEstado']").count() > 0 else "En Estudio"
        
        com_revisora = page.locator("[id*='lblComisionesRevisora']").first.text_content() if page.locator("[id*='lblComisionesRevisora']").count() > 0 else "N/A"
        est_revisora = page.locator("[id*='lblEstadoRevisora']").first.text_content() if page.locator("[id*='lblEstadoRevisora']").count() > 0 else "N/A"

        media_sancion = "Sí" if "MEDIA SANCIÓN" in html_page.upper() else "No"
        fecha_act = datetime.now().strftime("%d/%m/%Y %H:%M")

        print("   ✔ ¡Datos extraídos con éxito!")

        return [
            exp_str,
            objeto.strip() if objeto else "Sin datos",
            autor.strip() if autor else "Sin datos",
            bloque.strip() if bloque else "Sin datos",
            com_origen.strip() if com_origen else "Sin asignación",
            est_origen.strip() if est_origen else "En Estudio",
            com_revisora.strip() if com_revisora else "N/A",
            est_revisora.strip() if est_revisora else "N/A",
            media_sancion,
            fecha_act
        ]

    except Exception as e:
        print(f"   ❌ Error procesando {exp_str}: {e}")
        return None

# 3. Lectura de expediente y volcado de resultados
sheet_origen = sh.sheet1
expedientes_origen = sheet_origen.col_values(1)[1:]

filas_para_consolidado = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    page = context.new_page()

    for exp in expedientes_origen:
        if exp.strip():
            datos = extraer_datos_expediente(page, exp)
            if datos:
                filas_para_consolidado.append(datos)

    browser.close()

if filas_para_consolidado:
    sheet_consolidado.append_rows(filas_para_consolidado)
    print(f"\n🎉 ¡Proceso finalizado! Se agregaron {len(filas_para_consolidado)} filas en 'Senado_PBA_Consolidado'.")
else:
    print("\n⚠️ No se obtuvieron registros nuevos.")
