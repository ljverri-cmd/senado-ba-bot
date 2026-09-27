import os
import json
import re
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

print("--- 🚀 INICIANDO BOT LEGISLATIVO PBA CON PLAYWRIGHT (DIPUTADOS + SENADO) ---")

# 1. Autenticación con Google Sheets
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

def consultar_expediente_playwright(page, expediente):
    exp_str = str(expediente).strip()
    match = re.search(r'([a-zA-Z]+)\s*[\-\/]?\s*(\d+)\s*[\-\/]?\s*([\d\-]+)', exp_str)
    
    if not match:
        print(f"⚠️ Formato no válido: '{exp_str}'")
        return None

    letra = match.group(1).upper()
    numero = match.group(2)
    periodo_raw = match.group(3)

    print(f"\n🔎 Buscando en la Web -> Letra: '{letra}', Nro: '{numero}', Período: '{periodo_raw}'")

    objeto, autor, estado = None, "Poder Ejecutivo PBA", "En Tramitación"

    # ESTRATEGIA 1: Consultar la Cámara de Diputados de PBA (Origen PE para letra E)
    try:
        origen_code = "PE" if letra in ["E", "PE"] else letra
        url_hcd = f"https://www.hcdiputados-ba.gov.ar/index.php?page=proyectos&search=proyecto&periodo={periodo_raw}&origen={origen_code}%20%20&numero={numero}&alcance=0"
        
        page.goto(url_hcd, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2000)

        body_text = page.inner_text("body")

        if len(body_text) > 100 and ("PROYECTO" in body_text or "LEY" in body_text or "DECLARANDO" in body_text):
            # Extraer párrafos descriptivos del DOM
            elementos = page.locator("p, td, div.contenido, table").all()
            for elem in elementos:
                txt = elem.inner_text().strip()
                if len(txt) > 30 and ("DECLARANDO" in txt or "MODIFICANDO" in txt or "ESTABLECIENDO" in txt or "CREANDO" in txt or "SOLICITANDO" in txt):
                    objeto = txt.replace("\n", " ")
                    break

            # Buscar comisiones
            for elem in elementos:
                txt = elem.inner_text().strip()
                if "COMISIÓN" in txt or "PRESUPUESTO" in txt or "LEGISLACIÓN" in txt:
                    estado = txt.replace("\n", " ")
                    break
    except Exception as e:
        print(f"   ⚠️ Error en consulta HCD: {e}")

    # ESTRATEGIA 2: Si no trajo resultados, navegar el portal del Senado
    if not objeto:
        try:
            url_senado = "https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx"
            page.goto(url_senado, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)

            # Clic en la solapa de Proyectos
            tab_p = page.locator("text=PROYECTOS").first
            if tab_p.is_visible():
                tab_p.click()
                page.wait_for_timeout(1500)

            # Completar formulario
            tipo_sel = page.locator("select[id*='ddlTipoP'], select[id*='ddlLetra']").first
            if tipo_sel.is_visible():
                try:
                    tipo_sel.select_option(value="PE" if letra == "E" else letra)
                except Exception:
                    tipo_sel.select_option(label="PE" if letra == "E" else letra)

            num_in = page.locator("input[id*='txtNumeroP'], input[id*='txtNumero']").first
            if num_in.is_visible():
                num_in.fill(numero)

            btn_bus = page.locator("input[id*='btnBuscarP'], input[value*='Buscar']").first
            if btn_bus.is_visible():
                btn_bus.click()
                page.wait_for_timeout(3000)

            # Extraer tabla de resultados
            filas_tabla = page.locator("table tr").all()
            for f in filas_tabla:
                f_txt = f.inner_text().strip()
                if numero in f_txt and "Calle 51" not in f_txt:
                    celdas = f.locator("td, th").all_inner_texts()
                    if len(celdas) >= 2:
                        objeto = celdas[1].replace("\n", " ")
                        if len(celdas) > 2:
                            autor = celdas[2]
                        if len(celdas) > 3:
                            estado = celdas[-1]
                        break
        except Exception as e:
            print(f"   ⚠️ Error en consulta Senado: {e}")

    if not objeto:
        print(f"   ⚠️ No se encontraron resultados en portales web para {exp_str}.")
        return None

    objeto_clean = re.sub(r'\s+', ' ', objeto)[:250]
    autor_clean = autor if autor else ("Poder Ejecutivo PBA" if letra in ["E", "PE"] else "Sin datos")
    bloque = "Poder Ejecutivo PBA" if letra in ["E", "PE"] else "Sin datos"
    com_origen = "Asuntos Constitucionales / Presupuesto e Impuestos"
    est_origen = estado.replace("\n", " ")[:150] if estado else "En Tramitación / Comisión"
    com_revisora = "N/A"
    est_revisora = "N/A"
    media_sancion = "No"
    fecha_act = datetime.now().strftime("%d/%m/%Y %H:%M")

    print(f"   ✔ ¡DATOS EXTRAÍDOS!: '{objeto_clean[:60]}...' | Estado: '{est_origen}'")

    return [
        exp_str,
        objeto_clean,
        autor_clean,
        bloque,
        com_origen,
        est_origen,
        com_revisora,
        est_revisora,
        media_sancion,
        fecha_act
    ]

# 3. Bucle Principal con Navegador Playwright Headless
sheet_origen = sh.sheet1
expedientes_origen = sheet_origen.col_values(1)[1:]

cont_agregados = 0

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = context.new_page()

    for exp in expedientes_origen:
        if exp.strip():
            try:
                datos = consultar_expediente_playwright(page, exp)
                if datos:
                    sheet_consolidado.append_row(datos)
                    cont_agregados += 1
                    print("   💾 Fila guardada exitosamente en Google Sheets.")
            except Exception as err_exp:
                print(f"   ❌ Error al procesar '{exp}': {err_exp}. Continuando...")

    browser.close()

print(f"\n🎉 Proceso finalizado. Total guardados: {cont_agregados}")
