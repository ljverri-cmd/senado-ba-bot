import os
import json
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

print("--- 🚀 INICIANDO BOT SENADO PBA (POST ASP.NET CON VIEWSTATE) ---")

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

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/x-www-form-urlencoded"
}

URL_BASE = "https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx"

# 2. Función para obtener datos reales del expediente
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
        # Paso A: Obtener la página inicial para capturar ViewState
        r_get = session.get(URL_BASE, headers=headers, timeout=20)
        soup_get = BeautifulSoup(r_get.text, "html.parser")

        def get_hidden_val(name):
            elem = soup_get.find("input", {"name": name})
            return elem["value"] if elem and elem.has_attr("value") else ""

        viewstate = get_hidden_val("__VIEWSTATE")
        viewstategen = get_hidden_val("__VIEWSTATEGENERATOR")
        eventvalidation = get_hidden_val("__EVENTVALIDATION")

        # Detectar el nombre real de los controles de formulario en el ASPX
        btn_buscar_name = "ctl00$PageContent$btnBuscarProyectos"
        input_num_name = "ctl00$PageContent$txtNumeroProyectos"
        select_letra_name = "ctl00$PageContent$ddlLetraProyectos"
        select_periodo_name = "ctl00$PageContent$ddlPeriodoProyectos"

        # Buscar inputs en el HTML si los nombres dinámicos varían
        for inp in soup_get.find_all(["input", "select"]):
            iname = inp.get("name", "")
            if "txtNumero" in iname or "Numero" in iname:
                input_num_name = iname
            elif "ddlLetra" in iname or "Tipo" in iname:
                select_letra_name = iname
            elif "ddlPeriodo" in iname or "Periodo" in iname:
                select_periodo_name = iname
            elif "btnBuscar" in iname or "Buscar" in iname:
                btn_buscar_name = iname

        # Paso B: Construir el Payload del POST
        payload = {
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstategen,
            "__EVENTVALIDATION": eventvalidation,
            select_letra_name: letra,
            input_num_name: numero,
            select_periodo_name: periodo,
            btn_buscar_name: "Buscar"
        }

        # Paso C: Enviar la consulta con el estado
        r_post = session.post(URL_BASE, data=payload, headers=headers, timeout=25)
        soup_post = BeautifulSoup(r_post.text, "html.parser")

        # Paso D: Extraer la información filtrada de la tabla
        objeto = None
        autor = None
        comision = None
        estado = None

        # Inspeccionar tablas en el HTML de respuesta
        tablas = soup_post.find_all("table")
        for tabla in tablas:
            filas = tabla.find_all("tr")
            for f in filas:
                celdas = [c.get_text(strip=True) for c in f.find_all(["td", "th"])]
                if len(celdas) >= 2:
                    texto_fila = " ".join(celdas)
                    if "Objeto" in celdas[0] or "Carátula" in celdas[0]:
                        objeto = celdas[1]
                    elif "Autor" in celdas[0] or "Iniciador" in celdas[0]:
                        autor = celdas[1]
                    elif "Comisión" in celdas[0]:
                        comision = celdas[1]
                    elif "Estado" in celdas[0]:
                        estado = celdas[1]

        # Si viene en formato de grilla horizontal (filas de datos)
        if not objeto:
            for tabla in tablas:
                filas = tabla.find_all("tr")
                if len(filas) > 1:
                    headers_tabla = [h.get_text(strip=True).upper() for h in filas[0].find_all(["td", "th"])]
                    if any("EXPEDIENTE" in h or "SUMARIO" in h or "PROYECTO" in h for h in headers_tabla):
                        datos_fila = [c.get_text(strip=True) for c in filas[1].find_all("td")]
                        if len(datos_fila) >= 3:
                            objeto = datos_fila[1] if len(datos_fila) > 1 else None
                            autor = datos_fila[2] if len(datos_fila) > 2 else None
                            comision = datos_fila[3] if len(datos_fila) > 3 else None
                            estado = datos_fila[4] if len(datos_fila) > 4 else None
                            break

        if not objeto and ("No se encontraron" in r_post.text or "Sin registros" in r_post.text):
            print("   ⚠️ No existen registros para este expediente en el Senado.")
            return None

        objeto = objeto if objeto else "Ver ficha en portal oficial"
        autor = autor if autor else "Sin datos"
        bloque = "Sin datos"
        com_origen = comision if comision else "Sin asignación"
        est_origen = estado if estado else "En Estudio"
        com_revisora = "N/A"
        est_revisora = "N/A"
        media_sancion = "Sí" if "MEDIA SANCIÓN" in r_post.text.upper() else "No"
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
