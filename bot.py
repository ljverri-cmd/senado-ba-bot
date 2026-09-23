import os
import json
import re
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

print("--- 🚀 INICIANDO BOT SENADO PBA (VERSIÓN DEFINITIVA) ---")

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

# 2. Función de consulta optimizada
def extraer_datos_expediente(page, expediente):
    exp_str = str(expediente).strip()
    match = re.search(r'([a-zA-Z]+)\s*[\-\/]?\s*(\d+)\s*[\-\/]?\s*([\d\-]+)', exp_str)
    
    if not match:
        print(f"⚠️ Formato no válido: '{exp_str}'")
        return None

    letra = match.group(1).upper()
    numero = match.group(2)
    periodo_raw = match.group(3)

    # Extraer el año base (ej: si es "25-26" o "2025-2026", el año base es "2025")
    p1 = periodo_raw.split("-")[0].strip()
    p1_full = f"20{p1}" if len(p1) == 2 else p1

    print(f"\n🔎 Buscando en Senado PBA -> Letra: '{letra}', Nro: '{numero}', Año base: '{p1_full}'")

    try:
        page.goto("https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)

        # 1. Cambiar explícitamente a la pestaña "PROYECTOS" si existe el botón
        try:
            btn_proyectos = page.locator("input[value*='PROYECTOS'], button:has-text('PROYECTOS'), a:has-text('PROYECTOS')").first
            if btn_proyectos.is_visible():
                btn_proyectos.click(force=True, timeout=3000)
                page.wait_for_timeout(1000)
        except Exception:
            pass

        # 2. Inyección de datos mediante JS evitando bloqueos por controles ocultos
        page.evaluate(f"""() => {{
            // Seleccionar Letra
            const ddlLetra = document.querySelector("select[id*='ddlLetrasExpedientes'], select[name*='ddlLetras'], select[id*='ddlLetra']");
            if (ddlLetra) {{
                for (let opt of ddlLetra.options) {{
                    if (opt.text.trim().startsWith('{letra}') || opt.value === '{letra}') {{
                        ddlLetra.value = opt.value;
                        ddlLetra.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        break;
                    }}
                }}
            }}

            // Inserción del Número
            const txtNum = document.querySelector("input[id*='txtNumeroExpediente'], input[name*='txtNumero']");
            if (txtNum) {{
                txtNum.value = '{numero}';
                txtNum.dispatchEvent(new Event('input', {{ bubbles: true }}));
            }}

            // Seleccionar Período flexible por año base
            const ddlPeriodo = document.querySelector("select[id*='ddlPeriodo'], select[name*='ddlPeriodo']");
            if (ddlPeriodo) {{
                for (let opt of ddlPeriodo.options) {{
                    if (opt.text.includes('{p1_full}') || opt.value.includes('{p1_full}')) {{
                        ddlPeriodo.value = opt.value;
                        ddlPeriodo.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        break;
                    }}
                }}
            }}
        }}""")

        page.wait_for_timeout(500)

        # 3. Hacer clic en el botón de búsqueda
        btn_buscar = page.locator("input[type='submit'][value*='Buscar'], input[id*='btnBuscar'], button:has-text('Buscar')").first
        if btn_buscar.count() > 0:
            btn_buscar.click(force=True, timeout=5000)
        else:
            page.evaluate("() => { const b = document.querySelector(\"input[type='submit']\"); if(b) b.click(); }")

        # Esperar a que AJAX refresque la tabla
        page.wait_for_timeout(4000)

        # 4. Extraer información filtrando elementos institucionales/footer
        objeto, autor, comision, estado = None, None, None, None

        filas = page.locator("table.grid-view tr, table[id*='Grid'] tr, div[id*='Resultado'] table tr").all()
        if len(filas) == 0:
            filas = page.locator("table tr").all()

        for f in filas:
            txt = f.inner_text().strip()
            # Omitir el pie de página institucional de La Plata
            if "Calle 51" in txt or "Honorable Senado" in txt or "Teléfono" in txt:
                continue

            if numero in txt:
                celdas = [c.strip() for c in txt.split("\t") if c.strip()]
                for celda in celdas:
                    if len(celda) > 15 and not any(k in celda for k in ["Calle 51", "La Plata", "Teléfono"]) and not objeto:
                        objeto = celda
                    elif any(tit in celda for tit in ["Senador", "Diputado", "Bloque", "P.E."]) and not autor:
                        autor = celda
                    elif "Comisión" in celda and not comision:
                        comision = celda
                    elif any(est in celda for est in ["En Estudio", "Aprobado", "Sancionado", "Archivado", "Giro"]) and not estado:
                        estado = celda

        # Fallback si el resultado viene en contenedores de texto
        if not objeto:
            elementos_texto = page.locator("div[id*='ContentPlaceHolder'], div[id*='UpdatePanel']").all_inner_texts()
            for bloque in elementos_texto:
                lineas = [l.strip() for l in bloque.split("\n") if len(l.strip()) > 15]
                for l in lineas:
                    if "Calle 51" not in l and "Honorable Senado" not in l and not any(k in l.upper() for k in ["BUSCAR", "LEGISLATIVA", "PERÍODO"]):
                        objeto = l
                        break
                if objeto:
                    break

        if not objeto:
            print(f"   ⚠️ No se encontraron resultados para {exp_str}.")
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

        print(f"   ✔ ¡DATOS EXTRAÍDOS!: '{objeto[:45]}...' | Estado: '{est_origen}'")

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

# 3. Bucle principal de ejecución
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
                print("   💾 Fila guardada exitosamente en Google Sheets.")

    browser.close()

print(f"\n🎉 Proceso finalizado. Total guardados: {cont_agregados}")
