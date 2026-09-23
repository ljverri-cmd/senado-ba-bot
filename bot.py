import os
import json
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

print("--- 🚀 INICIANDO BOT SENADO PBA (HTTP CONSULTA DIRECTA) ---")

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

# 2. Función de consulta HTTP directa
def consultar_expediente(expediente):
    exp_str = str(expediente).strip()
    match = re.search(r'([a-zA-Z]+)\s*[\-\/]?\s*(\d+)\s*[\-\/]?\s*([\d\-]+)', exp_str)
    
    if not match:
        print(f"⚠️ Formato no válido: '{exp_str}'")
        return None

    letra = match.group(1).upper()
    numero = match.group(2)
    periodo_raw = match.group(3)

    # Convertir "24-25" o "24" a año de 4 dígitos
    p1 = periodo_raw.split("-")[0].strip()
    p1_full = f"20{p1}" if len(p1) == 2 else p1

    print(f"\n🔎 Buscando en Senado PBA -> Letra: '{letra}', Nro: '{numero}', Año: '{p1_full}'")

    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    url_base = "https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx"

    try:
        # Petición GET para obtener tokens ASP.NET y opciones de períodos
        resp_get = session.get(url_base, headers=headers, timeout=20)
        soup_get = BeautifulSoup(resp_get.text, 'html.parser')

        viewstate = soup_get.find("input", {"id": "__VIEWSTATE"})
        eventvalidation = soup_get.find("input", {"id": "__EVENTVALIDATION"})

        # Buscar el valor exacto del 'option' en el desplegable de períodos que contenga el año
        periodo_val = p1_full
        ddl_periodo = soup_get.find("select", id=re.compile(r'ddlPeriodo', re.I))
        if ddl_periodo:
            for opt in ddl_periodo.find_all("option"):
                if p1_full in opt.text or p1 in opt.text:
                    periodo_val = opt.get("value", opt.text)
                    break

        # Construir payload simulando la búsqueda en la sección de Proyectos
        payload = {
            "__VIEWSTATE": viewstate["value"] if viewstate else "",
            "__EVENTVALIDATION": eventvalidation["value"] if eventvalidation else "",
            "ctl00$ContentPlaceHolder1$rdbTipoBusqueda": "Proyectos",
            "ctl00$ContentPlaceHolder1$ddlTipoP": letra,
            "ctl00$ContentPlaceHolder1$txtNumeroP": numero,
            "ctl00$ContentPlaceHolder1$ddlPeriodoP": periodo_val,
            "ctl00$ContentPlaceHolder1$btnBuscarP": "Buscar"
        }

        resp_post = session.post(url_base, data=payload, headers=headers, timeout=25)
        soup_post = BeautifulSoup(resp_post.text, 'html.parser')

        # Extraer filas de resultados
        tabla = soup_post.find("table", class_=re.compile(r'grid|tabla|resultado', re.I)) or soup_post.find("table")
        
        objeto, autor, comision, estado = None, None, None, None

        if tabla:
            for fila in tabla.find_all("tr"):
                texto_fila = fila.get_text(strip=True)
                if "Calle 51" in texto_fila or "Teléfono" in texto_fila:
                    continue
                if numero in texto_fila:
                    celdas = [td.get_text(strip=True) for td in fila.find_all(["td", "th"])]
                    if len(celdas) >= 2:
                        objeto = celdas[1] if len(celdas) > 1 else celdas[0]
                        autor = celdas[2] if len(celdas) > 2 else "Sin datos"
                        estado = celdas[-1] if len(celdas) > 3 else "En Estudio"

        # Fallback de búsqueda de texto general
        if not objeto:
            bloques = soup_post.find_all("div", id=re.compile(r'ContentPlaceHolder|UpdatePanel', re.I))
            for b in bloques:
                txt = b.get_text()
                if numero in txt and "Calle 51" not in txt:
                    lineas = [l.strip() for l in txt.split("\n") if len(l.strip()) > 20]
                    if lineas:
                        objeto = lineas[0]
                        break

        if not objeto:
            print(f"   ⚠️ No se encontraron resultados para {exp_str}.")
            return None

        objeto = objeto if objeto else "Proyecto registrado"
        autor = autor if autor else "Sin datos"
        bloque = "Sin datos"
        com_origen = "Sin asignación"
        est_origen = estado if estado else "En Estudio"
        com_revisora = "N/A"
        est_revisora = "N/A"
        media_sancion = "Sí" if "MEDIA SANCIÓN" in resp_post.text.upper() else "No"
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

    except Exception as err:
        print(f"   ❌ Error al realizar la solicitud HTTP: {err}")
        return None

# 3. Bucle de ejecución
sheet_origen = sh.sheet1
expedientes_origen = sheet_origen.col_values(1)[1:]

cont_agregados = 0

for exp in expedientes_origen:
    if exp.strip():
        datos = consultar_expediente(exp)
        if datos:
            sheet_consolidado.append_row(datos)
            cont_agregados += 1
            print("   💾 Fila guardada exitosamente en Google Sheets.")

print(f"\n🎉 Proceso finalizado. Total guardados: {cont_agregados}")
