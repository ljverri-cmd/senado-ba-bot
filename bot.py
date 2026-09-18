import os
import json
import re
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

print("--- 🚀 INICIANDO BOT CON NAVEGACIÓN Y APERTURA DE EXPEDIENTE SENADO PBA ---")

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

# 2. Extracción de datos ingresando al detalle del resultado
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
        # Cargar el buscador oficial
        page.goto("https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1000)

        # Seleccionar la pestaña/radiobutton de "Proyectos" si existe
        rdb_proyectos = page.locator("input[value*='Proyecto'], input[id*='rdbProyecto'], label:has-text('Proyectos')")
        if rdb_proyectos.count() > 0:
            try:
                rdb_proyectos.first.click()
                page.wait_for_timeout(500)
            except Exception:
                pass

        # Llenar selectores del formulario
        sec_numero = page.locator("input[id*='txtNumero'], input[name*='txtNumero']").first
        sec_numero.wait_for(state="visible", timeout=10000)
        sec_numero.fill(numero)

        sec_tipo = page.locator("select[id*='ddlTipo'], select[name*='ddlTipo']").first
        if sec_tipo.count() > 0:
            try:
                sec_tipo.select_option(value=letra)
            except Exception:
                try:
                    sec_tipo.select_option(label=letra)
                except Exception:
                    pass

        sec_periodo = page.locator("select[id*='ddlPeriodo'], select[name*='ddlPeriodo']").first
        if sec_periodo.count() > 0:
            try:
                sec_periodo.select_option(label=periodo)
            except Exception:
                try:
                    sec_periodo.select_option(value=periodo)
                except Exception:
                    pass

        # Clic explícito en Buscar
        btn_buscar = page.locator("input[type='submit'][value*='Buscar'], input[id*='btnBuscar'], a[id*='btnBuscar'], button:has-text('Buscar')").first
        btn_buscar.click()

        # Esperar PostBack y renderizado de la grilla de resultados
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)

        html_page = page.content()

        if "No se encontraron" in html_page or "Sin resultados" in html_page:
            print("   ⚠️ No se encontraron resultados para este expediente.")
            return None

        # Si aparece la grilla de resultados, hacer clic en el expediente para abrir el detalle
        enlace_expediente = page.locator("table td a, .grid-view a, a[href*='javascript']").first
        if enlace_expediente.count() > 0:
            print("   📄 Abriendo el detalle del expediente...")
            enlace_expediente.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(3000)

        # Capturar el texto completo del contenedor del resultado o de toda la página
        texto_pagina = page.inner_text("body")

        # Expresiones regulares para extraer los campos clave desde el texto plano renderizado
        def buscar_campo(patrones, texto):
            for pat in patrones:
                m = re.search(f"{pat}[:\\s]+([^\\n\\r]+)", texto, re.IGNORECASE)
                if m:
                    val = m.group(1).strip()
                    if val and len(val) > 1:
                        return val
            return None

        objeto = buscar_campo(["Objeto", "Sumario", "Carátula", "Extracto", "Proyecto"], texto_pagina)
        autor = buscar_campo(["Autor", "Iniciador", "Firmante", "Senador"], texto_pagina)
        bloque = buscar_campo(["Bloque", "Partido", "Bloque Político"], texto_pagina)
        com_origen = buscar_campo(["Comisión", "Comisiones", "Giro a comisión"], texto_pagina)
        est_origen = buscar_campo(["Estado", "Estado en comisión", "Situación"], texto_pagina)
        
        # Fallback si no se encontró con Regex
        if not objeto:
            # Extraer los primeros párrafos útiles
            lineas = [l.strip() for l in texto_pagina.split("\n") if len(l.strip()) > 20]
            objeto = lineas[0] if lineas else "Ver ficha en la web"

        objeto = objeto if objeto else "Ver ficha en la web"
        autor = autor if autor else "Sin datos"
        bloque = bloque if bloque else "Sin datos"
        com_origen = com_origen if com_origen else "Sin asignación"
        est_origen = est_origen if est_origen else "En Estudio"

        com_revisora = "N/A"
        est_revisora = "N/A"
        media_sancion = "Sí" if "MEDIA SANCIÓN" in texto_pagina.upper() else "No"
        fecha_act = datetime.now().strftime("%d/%m/%Y %H:%M")

        print(f"   ✔ Extraído: Objeto='{objeto[:40]}...', Autor='{autor}'")

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

# 3. Bucle de ejecución y guardado inmediato
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

print(f"\n🎉 ¡Proceso finalizado! Se actualizaron {cont_agregados} filas en Google Sheets.")
