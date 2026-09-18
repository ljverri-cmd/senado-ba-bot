import os
import json
import re
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

print("--- 🚀 INICIANDO BOT SENADO PBA (CAPTURA POR POSTBACK E GRIDVIEW) ---")

# 1. Autenticação e conexão com Google Sheets
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

# 2. Extractor de datos con manejo de detalles y PostBack
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

    print(f"\n🔎 Consultando expediente: {exp_str} -> Letra: '{letra}', Nro: '{numero}', Período: '{periodo}'")

    try:
        page.goto("https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)

        # Campos de formulario
        input_numero = page.locator("input[id*='txtNumero'], input[name*='Numero']").first
        input_numero.wait_for(state="visible", timeout=15000)

        select_tipo = page.locator("select[id*='ddlTipo'], select[name*='Tipo']").first
        if select_tipo.count() > 0:
            try:
                select_tipo.select_option(value=letra)
            except Exception:
                try:
                    select_tipo.select_option(label=letra)
                except Exception:
                    pass

        input_numero.fill(numero)

        select_periodo = page.locator("select[id*='ddlPeriodo'], select[name*='Periodo']").first
        if select_periodo.count() > 0:
            try:
                select_periodo.select_option(label=periodo)
            except Exception:
                try:
                    select_periodo.select_option(value=periodo)
                except Exception:
                    pass

        # Disparar búsqueda
        print("   🚀 Enviando formulario de búsqueda...")
        input_numero.press("Enter")

        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2500)

        html_page = page.content()

        if "No se encontraron registros" in html_page or "Sin resultados" in html_page:
            print("   ⚠️ No se encontraron resultados para este expediente.")
            return None

        # Intentar hacer clic en el enlace del expediente si existe la grilla
        # Usamos timeout=5000 dentro de try/except para evitar bloqueos de 30s
        seletor_link = "table[id*='Grid'] a, table[id*='grd'] a, .table a, a[id*='lnk'], a[id*='btn']"
        link_resultado = page.locator(seletor_link).first

        try:
            if link_resultado.is_visible(timeout=5000):
                print("   📄 Abriendo ficha de detalle...")
                link_resultado.click(timeout=5000)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2000)
        except Exception:
            print("   ℹ️ No fue necesario hacer clic en el detalle (información presente en la grilla principal).")

        # Captura de texto del cuerpo
        texto_cuerpo = page.inner_text("body")

        def buscar_regex(patrones, texto):
            for pat in patrones:
                m = re.search(f"{pat}[:\\s]+([^\\n\\r]+)", texto, re.IGNORECASE)
                if m:
                    val = m.group(1).strip()
                    if val and len(val) > 1:
                        return val
            return None

        objeto = buscar_regex(["Objeto", "Sumario", "Carátula", "Extracto", "Proyecto"], texto_cuerpo)
        autor = buscar_regex(["Autor", "Iniciador", "Firmante", "Senador"], texto_cuerpo)
        bloque = buscar_regex(["Bloque", "Partido", "Bloque Político"], texto_cuerpo)
        com_origen = buscar_regex(["Comisión", "Comisiones", "Giro a comisión"], texto_cuerpo)
        est_origen = buscar_regex(["Estado", "Estado en comisión", "Situación"], texto_cuerpo)

        if not objeto:
            lineas_validas = [linea.strip() for linea in texto_cuerpo.split("\n") if len(linea.strip()) > 25]
            objeto = lineas_validas[0] if lineas_validas else "Ver ficha en la web"

        objeto = objeto if objeto else "Ver ficha en la web"
        autor = autor if autor else "Sin datos"
        bloque = bloque if bloque else "Sin datos"
        com_origen = com_origen if com_origen else "Sin asignación"
        est_origen = est_origen if est_origen else "En Estudio"

        com_revisora = "N/A"
        est_revisora = "N/A"
        media_sancion = "Sí" if "MEDIA SANCIÓN" in texto_cuerpo.upper() else "No"
        fecha_act = datetime.now().strftime("%d/%m/%Y %H:%M")

        print(f"   ✔ Extracción exitosa: Objeto='{objeto[:35]}...', Autor='{autor}'")

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

# 3. Guardado en Google Sheets
sheet_origen = sh.sheet1
expedientes_origen = sheet_origen.col_values(1)[1:]

cont_agregados = 0

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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

print(f"\n🎉 ¡Proceso finalizado! Se procesaron {cont_agregados} expedientes.")
