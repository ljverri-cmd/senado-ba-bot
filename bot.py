import os
import json
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

print("--- 🚀 INICIANDO BOT SENADO PBA (ASP.NET AJAX UPDATEPANEL) ---")

# 1. Conexión con Google Sheets
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

URL_BASE = "https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx"

# 2. Función de consulta con simulación AJAX
def extraer_datos_expediente(session, expediente):
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
        # A. Cargar la página inicial para obtener el ViewState original
        headers_init = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        r_get = session.get(URL_BASE, headers=headers_init, timeout=20)
        soup_get = BeautifulSoup(r_get.text, "html.parser")

        def get_hidden_val(name):
            elem = soup_get.find("input", {"name": name})
            return elem["value"] if elem and elem.has_attr("value") else ""

        viewstate = get_hidden_val("__VIEWSTATE")
        viewstategen = get_hidden_val("__VIEWSTATEGENERATOR")
        eventvalidation = get_hidden_val("__EVENTVALIDATION")

        # B. Identificar dinámicamente los controles de la página
        input_num_name = "ctl00$PageContent$txtNumero"
        select_letra_name = "ctl00$PageContent$ddlTipo"
        select_periodo_name = "ctl00$PageContent$ddlPeriodo"
        btn_buscar_name = "ctl00$PageContent$btnBuscar"
        script_manager_name = "ctl00$ScriptManager1"

        for inp in soup_get.find_all(["input", "select"]):
            iname = inp.get("name", "")
            if "txtNumero" in iname or "Numero" in iname:
                input_num_name = iname
            elif "ddlTipo" in iname or "ddlLetra" in iname or "Tipo" in iname:
                select_letra_name = iname
            elif "ddlPeriodo" in iname or "Periodo" in iname:
                select_periodo_name = iname
            elif "btnBuscar" in iname or "Buscar" in iname:
                btn_buscar_name = iname

        # C. Construir los encabezados AJAX obligatorios para WebForms
        headers_ajax = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "X-MicrosoftAjax": "Delta=true",
            "Cache-Control": "no-cache",
            "Referer": URL_BASE
        }

        # D. Payload con el UpdatePanel activo
        payload = {
            script_manager_name: f"ctl00$PageContent$UpdatePanel1|{btn_buscar_name}",
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstategen,
            "__EVENTVALIDATION": eventvalidation,
            select_letra_name: letra,
            input_num_name: numero,
            select_periodo_name: periodo,
            "__ASYNCPOST": "true",
            btn_buscar_name: "Buscar"
        }

        # E. Enviar la llamada AJAX
        r_post = session.post(URL_BASE, data=payload, headers=headers_ajax, timeout=25)
        html_respuesta = r_post.text

        soup_post = BeautifulSoup(html_respuesta, "html.parser")

        # F. Extraer datos del resultado
        objeto = None
        autor = None
        comision = None
        estado = None

        # Parsear todas las tablas generadas
        tablas = soup_post.find_all("table")
        for tabla in tablas:
            filas = tabla.find_all("tr")
            if len(filas) > 1:
                # Si es una grilla horizontal
                headers_tabla = [h.get_text(strip=True).upper() for h in filas[0].find_all(["td", "th"])]
                datos_fila = [c.get_text(strip=True) for c in filas[1].find_all("td")]
                
                if len(datos_fila) >= 2:
                    for i, head in enumerate(headers_tabla):
                        if i < len(datos_fila):
                            val = datos_fila[i]
                            if "OBJETO" in head or "SUMARIO" in head or "CARÁTULA" in head:
                                objeto = val
                            elif "AUTOR" in head or "INICIADOR" in head:
                                autor = val
                            elif "COMISIÓN" in head:
                                comision = val
                            elif "ESTADO" in head:
                                estado = val

        # Fallback de búsqueda Regex en el bloque delta de respuesta si no vino como tabla estándar
        if not objeto:
            m_obj = re.search(r'(?:Objeto|Sumario|Carátula)[:\s]+([^\r\n\|<]+)', html_respuesta, re.IGNORECASE)
            if m_obj:
                objeto = m_obj.group(1).strip()

            m_aut = re.search(r'(?:Autor|Iniciador)[:\s]+([^\r\n\|<]+)', html_respuesta, re.IGNORECASE)
            if m_aut:
                autor = m_aut.group(1).strip()

            m_est = re.search(r'(?:Estado|Situación)[:\s]+([^\r\n\|<]+)', html_respuesta, re.IGNORECASE)
            if m_est:
                estado = m_est.group(1).strip()

        if "No se encontraron" in html_respuesta or "Sin registros" in html_respuesta:
            print("   ⚠️ No existen registros para este expediente en el Senado.")
            return None

        objeto = objeto if objeto else "Ver ficha en el portal del Senado"
        autor = autor if autor else "Sin datos"
        bloque = "Sin datos"
        com_origen = comision if comision else "Sin asignación"
        est_origen = estado if estado else "En Estudio"
        com_revisora = "N/A"
        est_revisora = "N/A"
        media_sancion = "Sí" if "MEDIA SANCIÓN" in html_respuesta.upper() else "No"
        fecha_act = datetime.now().strftime("%d/%m/%Y %H:%M")

        print(f"   ✔ Extraído REAL: Objeto='{objeto[:40]}...', Autor='{autor}', Estado='{est_origen}'")

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
session = requests.Session()

for exp in expedientes_origen:
    if exp.strip():
        datos = extraer_datos_expediente(session, exp)
        if datos:
            sheet_consolidado.append_row(datos)
            cont_agregados += 1
            print("   💾 Fila guardada correctamente en Google Sheets.")

print(f"\n🎉 ¡Proceso finalizado! Se procesaron {cont_agregados} expedientes reales.")
