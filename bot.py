import os
import json
import re
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

print("--- 🚀 INICIANDO BOT SENADO PBA (PLAYWRIGHT DIAGNÓSTICO AVANZADO) ---")

# 1. Autenticación y conexión con Google Sheets
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

# 2. Función de consulta e interacción web
def extraer_datos_expediente(page, expediente):
    exp_str = str(expediente).strip()
    match = re.search(r'([a-zA-Z]+)\s*[\-\/]?\s*(\d+)\s*[\-\/]?\s*([\d\-]+)', exp_str)
    
    if not match:
        print(f"⚠️ Formato no válido: '{exp_str}'")
        return None

    letra = match.group(1).upper()
    numero = match.group(2)
    periodo_raw = match.group(3)

    if "-" in periodo_raw and len(periodo_raw) == 5:
        p1, p2 = periodo_raw.split("-")
        periodo = f"20{p1}-20{p2}"
    else:
        periodo = periodo_raw

    print(f"\n🔎 Consultando expediente: {exp_str} -> Letra: '{letra}', Nro: '{numero}', Período: '{periodo}'")

    try:
        # Cargar sitio web
        page.goto("https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)

        # Buscar si la consulta está atrapada dentro de un iframe
        iframes = page.frames
        frame_target = page
        for frame in iframes:
            if "Leyes" in frame.url or "proyecto" in frame.url.lower():
                frame_target = frame
                print(f"   ℹ️ Detectado iframe de trabajo: {frame.url}")
                break

        # Llenar número
        input_num = frame_target.locator("input[id*='txtNumero'], input[name*='Numero']").first
        input_num.wait_for(state="visible", timeout=10000)
        input_num.fill("")
        input_num.fill(numero)

        # Seleccionar letra/tipo
        select_letra = frame_target.locator("select[id*='ddlTipo'], select[id*='ddlLetra'], select[name*='Tipo']").first
        if select_letra.count() > 0:
            try:
                select_letra.select_option(value=letra)
            except Exception:
                try:
                    select_letra.select_option(label=letra)
                except Exception:
                    pass

        # Seleccionar período/año
        select_periodo = frame_target.locator("select[id*='ddlPeriodo'], select[name*='Periodo']").first
        if select_periodo.count() > 0:
            try:
                select_periodo.select_option(label=periodo)
            except Exception:
                try:
                    select_periodo.select_option(value=periodo)
                except Exception:
                    pass

        # Hacer clic en Buscar
        btn_buscar = frame_target.locator("input[type='submit'][value*='Buscar'], button:has-text('Buscar'), input[id*='btnBuscar']").first
        if btn_buscar.count() > 0:
            btn_buscar.click()
        else:
            input_num.press("Enter")

        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(4000)

        # Diagnóstico: Imprimir fragmento del contenido obtenido
        texto_pagina = frame_target.inner_text("body")
        print("   --- 📋 FRAGMENTO DEL TEXTO EN PÁGINA ---")
        lineas = [l.strip() for l in texto_pagina.split("\n") if l.strip()]
        for l in lineas[:12]: # Muestra las primeras 12 líneas reales del DOM
            print(f"   | {l}")
        print("   ----------------------------------------")

        # Parsear tabla de resultados
        filas_grid = frame_target.locator("table tr").all()
        
        objeto, autor, comision, estado = None, None, None, None

        if len(filas_grid) > 1:
            for fila in filas_grid:
                txt_row = fila.inner_text()
                if numero in txt_row or letra in txt_row or "Objeto" in txt_row or len(txt_row) > 30:
                    celdas = [c.strip() for c in txt_row.split("\t") if c.strip()]
                    if len(celdas) >= 2:
                        objeto = celdas[1] if len(celdas) > 1 else None
                        autor = celdas[2] if len(celdas) > 2 else None
                        comision = celdas[3] if len(celdas) > 3 else None
                        estado = celdas[4] if len(celdas) > 4 else None
                        break

        objeto = objeto if objeto else "Ver ficha en portal"
        autor = autor if autor else "Sin datos"
        bloque = "Sin datos"
        com_origen = comision if comision else "Sin asignación"
        est_origen = estado if estado else "En Estudio"
        com_revisora = "N/A"
        est_revisora = "N/A"
        media_sancion = "Sí" if "MEDIA SANCIÓN" in texto_pagina.upper() else "No"
        fecha_act = datetime.now().strftime("%d/%m/%Y %H:%M")

        print(f"   ✔ Resultado obtenido: Objeto='{objeto[:35]}...', Estado='{est_origen}'")

        return [
            exp_str,
            objeto,
            autor,
            bloque,
            com_origen,
            est_origen,
            com_revisora,
            est_revisora,
            media_sancion,
            fecha_act
        ]

    except Exception as e:
        print(f"   ❌ Error procesando {exp_str}: {e}")
        return None

# 3. Bucle de ejecución
sheet_origen = sh.sheet1
expedientes_origen = sheet_origen.col_values(1)[1:]

cont_agregados = 0

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-setuid-sandbox"]
    )
    context = browser.new_context(
        viewport={"width": 1366, "height": 768},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = context.new_page()

    for exp in expedientes_origen:
        if exp.strip():
            datos = extraer_datos_expediente(page, exp)
            if datos:
                sheet_consolidado.append_row(datos)
                cont_agregados += 1
                print("   💾 Fila guardada correctamente en Google Sheets.")

    browser.close()

print(f"\n🎉 Proceso finalizado. Total procesados: {cont_agregados}")
