import os
import json
import re
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

print("--- 🚀 INICIANDO BOT LEGISLATIVO PBA (SOPORTE AVANZADO AJAX + NORMALIZACIÓN DE AÑOS) ---")

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

    # Normalizar período a años completos de 4 dígitos
    if "-" in periodo_raw:
        p1, p2 = [p.strip() for p in periodo_raw.split("-")]
        p1_full = f"20{p1}" if len(p1) == 2 else p1
        p2_full = f"20{p2}" if len(p2) == 2 else p2
        periodo_normalizado = f"{p1_full}-{p2_full}"
        anio_inicio = p1_full
    else:
        anio_inicio = f"20{periodo_raw}" if len(periodo_raw) == 2 else periodo_raw
        periodo_normalizado = anio_inicio

    print(f"\n🔎 Buscando -> Letra: '{letra}', Nro: '{numero}', Período: '{periodo_raw}' (Año inicio: {anio_inicio})")

    objeto, autor, estado = None, "Poder Ejecutivo PBA", "En Tramitación"

    # ESTRATEGIA 1: Portal del Senado PBA con manipulación de DOM directa
    try:
        url_senado = "https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx"
        page.goto(url_senado, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(2000)

        # Inyectar y seleccionar los campos dinámicos
        page.evaluate(f"""() => {{
            // Seleccionar Solapa Proyectos si existe
            const btnProy = Array.from(document.querySelectorAll('a, button, input')).find(el => el.textContent.includes('PROYECTOS') || el.value === 'Proyectos');
            if (btnProy) btnProy.click();
        }}""")
        page.wait_for_timeout(1000)

        # Seleccionar Tipo, Número y Año
        page.evaluate(f"""() => {{
            const letraBuscada = '{letra}' === 'E' ? 'PE' : '{letra}';
            
            // 1. Tipo / Letra
            const selectTipo = document.querySelector("select[id*='ddlTipo'], select[id*='ddlLetra']");
            if (selectTipo) {{
                for (let opt of selectTipo.options) {{
                    if (opt.text.trim().startsWith(letraBuscada) || opt.value.trim() === letraBuscada) {{
                        selectTipo.value = opt.value;
                        selectTipo.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        break;
                    }}
                }}
            }}

            // 2. Número
            const inputNum = document.querySelector("input[id*='txtNumero']");
            if (inputNum) {{
                inputNum.value = '{numero}';
                inputNum.dispatchEvent(new Event('input', {{ bubbles: true }}));
            }}

            // 3. Período / Año
            const selectPeriodo = document.querySelector("select[id*='ddlPeriodo']");
            if (selectPeriodo) {{
                for (let opt of selectPeriodo.options) {{
                    if (opt.text.includes('{anio_inicio}') || opt.value.includes('{anio_inicio}')) {{
                        selectPeriodo.value = opt.value;
                        selectPeriodo.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        break;
                    }}
                }}
            }}
        }}""")

        page.wait_for_timeout(1000)

        # Disparar búsqueda
        btn_buscar = page.locator("input[id*='btnBuscar'], button[id*='btnBuscar'], input[value*='Buscar']").first
        if btn_buscar.is_visible():
            btn_buscar.click()
            page.wait_for_timeout(4000)

        # Extraer filas de la grilla de resultados
        filas = page.locator("table tr").all()
        for f in filas:
            txt = f.inner_text().strip()
            if numero in txt and "Calle 51" not in txt and "Honorable" not in txt:
                celdas = [c.strip() for c in txt.split("\t") if c.strip()]
                if len(celdas) >= 2:
                    objeto = celdas[1] if len(celdas) > 1 else celdas[0]
                    if len(celdas) > 2 and "Senador" in celdas[2]:
                        autor = celdas[2]
                    if len(celdas) > 3:
                        estado = celdas[-1]
                    break
    except Exception as e:
        print(f"   ⚠️ Intento en Senado no devolvió datos: {e}")

    # ESTRATEGIA 2: Consulta directa a la H. Cámara de Diputados de PBA si no se encontró en Senado
    if not objeto:
        try:
            origen_code = "PE" if letra in ["E", "PE"] else letra
            url_hcd = f"https://www.hcdiputados-ba.gov.ar/index.php?page=proyectos&search=proyecto&periodo={periodo_raw}&origen={origen_code}&numero={numero}&alcance=0"
            
            page.goto(url_hcd, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)

            # Buscar textos de extractos legislativos
            elementos = page.locator("td, p, div, span").all()
            for elem in elementos:
                txt = elem.inner_text().strip()
                if len(txt) > 35 and any(kw in txt for kw in ["DECLARANDO", "MODIFICANDO", "ESTABLECIENDO", "CREANDO", "SOLICITANDO", "PROYECTO DE LEY"]):
                    objeto = txt
                    break

            # Extraer comisiones / estado
            for elem in elementos:
                txt = elem.inner_text().strip()
                if any(kw in txt for kw in ["COMISIÓN DE", "PRESUPUESTO", "ASUNTOS CONSTITUCIONALES", "LEGISLACIÓN GENERAL"]):
                    estado = txt
                    break
        except Exception as e:
            print(f"   ⚠️ Intento en Diputados no devolvió datos: {e}")

    if not objeto:
        print(f"   ⚠️ No se encontraron datos en la web oficial para {exp_str}.")
        return None

    # Limpieza final del texto obtenido
    objeto_clean = re.sub(r'\s+', ' ', objeto)[:250]
    autor_clean = autor if autor else ("Poder Ejecutivo PBA" if letra in ["E", "PE"] else "Sin datos")
    bloque = "Poder Ejecutivo PBA" if letra in ["E", "PE"] else "Sin datos"
    com_origen = "Asuntos Constitucionales / Presupuesto e Impuestos"
    est_origen = estado.replace("\n", " ")[:150] if estado else "En Tramitación / Comisión"
    com_revisora = "N/A"
    est_revisora = "N/A"
    media_sancion = "No"
    fecha_act = datetime.now().strftime("%d/%m/%Y %H:%M")

    print(f"   ✔ ¡DATOS HALLADOS!: '{objeto_clean[:60]}...' | Estado: '{est_origen}'")

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

# 3. Bucle Principal
sheet_origen = sh.sheet1
expedientes_origen = sheet_origen.col_values(1)[1:]

cont_agregados = 0

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
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
                print(f"   ❌ Error procesando '{exp}': {err_exp}. Continuando...")

    browser.close()

print(f"\n🎉 Proceso finalizado. Total guardados: {cont_agregados}")
