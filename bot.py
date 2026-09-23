import os
import json
import re
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

print("--- 🚀 INICIANDO BOT SENADO PBA (VERSIÓN OPTIMIZADA) ---")

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

# 2. Función de consulta con selectores directos
def extraer_datos_expediente(page, expediente):
    exp_str = str(expediente).strip()
    match = re.search(r'([a-zA-Z]+)\s*[\-\/]?\s*(\d+)\s*[\-\/]?\s*([\d\-]+)', exp_str)
    
    if not match:
        print(f"⚠️ Formato no válido: '{exp_str}'")
        return None

    letra = match.group(1).upper()
    numero = match.group(2)
    periodo_raw = match.group(3)

    # Formatear el período para que coincida con el desplegable (ej. 2025 - 2026)
    if "-" in periodo_raw:
        partes = periodo_raw.split("-")
        p1 = partes[0].strip()
        p2 = partes[1].strip()
        if len(p1) == 2:
            p1 = f"20{p1}"
        if len(p2) == 2:
            p2 = f"20{p2}"
        periodo_fmt = f"{p1} - {p2}"
    else:
        periodo_fmt = periodo_raw if len(periodo_raw) == 4 else f"20{periodo_raw}"

    print(f"\n🔎 Buscando en Senado PBA -> Letra: '{letra}', Nro: '{numero}', Período: '{periodo_fmt}'")

    try:
        page.goto("https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)

        # Tratar de hacer clic en la solapa "Proyectos" si está visible y no causa timeout
        try:
            tab_proyectos = page.locator("#ctl00_ContentPlaceHolder1_btnProyectos, a[href*='Proyectos']").first
            if tab_proyectos.is_visible():
                tab_proyectos.click(timeout=5000)
                page.wait_for_timeout(1000)
        except Exception:
            pass # Si no interactúa, los campos de entrada igual están accesibles en la página

        # 1. Seleccionar la Letra / Tipo
        select_letra = page.locator("select[name*='ddlLetra'], select[name*='ddlTipo'], select[id*='ddl']").first
        if select_letra.count() > 0:
            options = select_letra.locator("option").all_inner_texts()
            for opt in options:
                if opt.strip().startswith(letra) or f"({letra})" in opt or opt.strip() == letra:
                    select_letra.select_option(label=opt)
                    break

        # 2. Inserción del Número de Expediente
        input_num = page.locator("input[name*='txtNumero'], input[id*='txtNumero']").first
        if input_num.count() > 0:
            input_num.fill(numero)

        # 3. Selección del Período
        select_periodo = page.locator("select[name*='ddlPeriodo'], select[id*='ddlPeriodo']").first
        if select_periodo.count() > 0:
            options_p = select_periodo.locator("option").all_inner_texts()
            for opt in options_p:
                if (p1 in opt if 'p1' in locals() else periodo_fmt in opt):
                    select_periodo.select_option(label=opt)
                    break

        # 4. Click en Buscar
        btn_buscar = page.locator("input[type='submit'][value*='Buscar'], input[name*='btnBuscar'], button:has-text('Buscar')").first
        btn_buscar.click()

        page.wait_for_timeout(4000)

        # 5. Extracción de resultados
        filas = page.locator("table tr").all()
        objeto, autor, comision, estado = None, None, None, None

        for f in filas:
            txt = f.inner_text()
            if numero in txt:
                celdas = [c.strip() for c in txt.split("\t") if c.strip()]
                if len(celdas) >= 2:
                    for celda in celdas:
                        if len(celda) > 20 and not objeto:
                            objeto = celda
                        elif any(tit in celda for tit in ["Senador", "Diputado", "Bloque", "P.E.", "P.E"]) and not autor:
                            autor = celda
                        elif "Comisión" in celda and not comision:
                            comision = celda
                        elif any(est in celda for est in ["En Estudio", "Aprobado", "Sancionado", "Archivado", "Giro"]) and not estado:
                            estado = celda

        # Fallback si los datos están estructurados como bloques de texto
        if not objeto:
            body_text = page.locator("body").inner_text()
            lineas = [l.strip() for l in body_text.split("\n") if len(l.strip()) > 20]
            for l in lineas:
                if numero in l or letra in l:
                    objeto = l
                    break

        if not objeto:
            print("   ⚠️ No se obtuvo respuesta para el expediente especificado.")
            return None

        objeto = objeto if objeto else "Proyecto registrado"
        autor = autor if autor else "Sin datos"
        bloque = "Sin datos"
        com_origen = comision if comision else "Sin asignación"
        est_origen = estado if estado else "En Estudio"
        com_revisora = "N/A"
        est_revisora = "N/A"
        media_sancion = "Sí" if "MEDIA SANCIÓN" in page.inner_text("body").upper() else "No"
        fecha_act = datetime.now().strftime("%d/%m/%Y %H:%M")

        print(f"   ✔ ¡DATOS ENCONTRADOS!: {objeto[:50]}...")

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

# 3. Ejecución principal
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
                print("   💾 Registrado en Google Sheets.")

    browser.close()

print(f"\n🎉 Proceso finalizado. Registros guardados: {cont_agregados}")
