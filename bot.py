import os
import json
import re
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

print("--- 🚀 INICIANDO BOT CON EXTRACCIÓN POR TABLA Y DOM SENADO PBA ---")

# 1. Autenticación y conexión a Google Sheets
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

# 2. Extracción robónstica del DOM
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

        selector_tipo = "select[id*='ddlTipo'], select[name*='ddlTipo']"
        selector_numero = "input[id*='txtNumero']:visible, input[name*='txtNumero']:visible"
        selector_periodo = "select[id*='ddlPeriodo'], select[name*='ddlPeriodo']"

        page.wait_for_selector(selector_numero, state="visible", timeout=15000)

        # Cargar formulario
        try:
            page.locator(selector_tipo).first.select_option(value=letra)
        except Exception:
            try:
                page.locator(selector_tipo).first.select_option(label=letra)
            except Exception:
                pass

        page.locator(selector_numero).first.fill(numero)

        if page.locator(selector_periodo).count() > 0:
            try:
                page.locator(selector_periodo).first.select_option(label=periodo)
            except Exception:
                try:
                    page.locator(selector_periodo).first.select_option(value=periodo)
                except Exception:
                    pass

        # Disparar búsqueda
        try:
            btn = page.locator("a[id*='btnBuscar'], input[id*='btnBuscar'], button[id*='btnBuscar'], .btn-buscar").first
            if btn.is_visible():
                btn.click()
            else:
                page.locator(selector_numero).first.press("Enter")
        except Exception:
            page.locator(selector_numero).first.press("Enter")

        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)

        html_page = page.content()

        if "No se encontraron registros" in html_page or "Sin resultados" in html_page:
            print("   ⚠️ No se encontraron resultados para este expediente.")
            return None

        # Estrategia 1: Búsqueda directa por etiquetas de ID ASP.NET
        def buscar_por_id_o_texto(patrones):
            for pat in patrones:
                loc = page.locator(f"[id*='{pat}'], [class*='{pat}']")
                if loc.count() > 0:
                    txt = loc.first.text_content().strip()
                    if txt and txt.upper() != "SIN DATOS":
                        return txt
            return None

        objeto = buscar_por_id_o_texto(["lblObjeto", "lblSumario", "lblCaratula", "lblExtracto", "Objeto", "Sumario"])
        autor = buscar_por_id_o_texto(["lblAutor", "lblIniciador", "lblFirmante", "Autor", "Iniciador"])
        bloque = buscar_por_id_o_texto(["lblBloque", "lblPartido", "Bloque"])
        com_origen = buscar_por_id_o_texto(["lblComisionesOrigen", "lblComision", "Comision"])
        est_origen = buscar_por_id_o_texto(["lblEstadoOrigen", "lblEstado", "Estado"])
        com_revisora = buscar_por_id_o_texto(["lblComisionesRevisora", "ComisionRev"])
        est_revisora = buscar_por_id_o_texto(["lblEstadoRevisora", "EstadoRev"])

        # Estrategia 2: Fallback mediante escaneo de la Tabla de Resultados (Grid)
        if not objeto or not autor:
            filas_tabla = page.locator("table tr")
            if filas_tabla.count() > 1:
                # Extraer texto de las celdas de la primera fila de datos
                celdas = filas_tabla.nth(1).locator("td")
                cant_celdas = celdas.count()
                
                if cant_celdas >= 3:
                    objeto = celdas.nth(1).text_content().strip() if not objeto else objeto
                    autor = celdas.nth(2).text_content().strip() if not autor else autor
                if cant_celdas >= 4 and not bloque:
                    bloque = celdas.nth(3).text_content().strip()
                if cant_celdas >= 5 and not est_origen:
                    est_origen = celdas.nth(4).text_content().strip()

        # Asignar valores por defecto si no se encontró información
        objeto = objeto if objeto else "Ver carátula en web"
        autor = autor if autor else "Sin datos"
        bloque = bloque if bloque else "Sin datos"
        com_origen = com_origen if com_origen else "Sin asignación"
        est_origen = est_origen if est_origen else "En Estudio"
        com_revisora = com_revisora if com_revisora else "N/A"
        est_revisora = est_revisora if est_revisora else "N/A"

        media_sancion = "Sí" if "MEDIA SANCIÓN" in html_page.upper() or "MEDIASANCION" in html_page.upper() else "No"
        fecha_act = datetime.now().strftime("%d/%m/%Y %H:%M")

        print(f"   ✔ Extraído exitosamente: Objeto='{objeto[:30]}...', Autor='{autor}'")

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

# 3. Guardado en tiempo real en Google Sheets
sheet_origen = sh.sheet1
expedientes_origen = sheet_origen.col_values(1)[1:]

cont_agregados = 0

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
                sheet_consolidado.append_row(datos)
                cont_agregados += 1
                print("   💾 Fila guardada correctamente con los datos extraídos.")

    browser.close()

print(f"\n🎉 ¡Proceso finalizado! Se completaron {cont_agregados} filas en Google Sheets.")
