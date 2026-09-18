import os
import json
import re
import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

print("--- 🚀 INICIANDO EXTRACCIÓN Y COMPILACIÓN DE PROYECTOS PBA ---")

# 1. Autenticación en Google Sheets
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
    
    # Crear o abrir la pestaña "Senado_PBA_Consolidado"
    try:
        sheet = sh.worksheet("Senado_PBA_Consolidado")
    except gspread.exceptions.WorksheetNotFound:
        sheet = sh.add_worksheet(title="Senado_PBA_Consolidado", rows="2000", cols="10")

    print(f"✔ Conectado a la planilla: '{sh.title}' | Hoja: 'Senado_PBA_Consolidado'")
except Exception as e:
    print(f"❌ Error de autenticación/Google Sheets: {e}")
    exit(1)

# 2. Encabezados exactos del cuadro
ENCABEZADOS = [
    "EXPEDIENTE LEGISLATIVO",
    "OBJETO",
    "AUTOR DEL PROYECTO",
    "BLOQUE",
    "COMISIONES ASIGNADAS CÁMARA DE ORIGEN",
    "ESTADO EN COMISIÓN CÁMARA DE ORIGEN",
    "COMISIONES ASIGNADAS CÁMARA REVISORA",
    "ESTADO EN COMISIÓN CÁMARA REVISORA",
    "MEDIA SANCIÓN",
    "FECHA ACTUALIZACIÓN"
]

# Inicializar/Asegurar la Fila 1 de la hoja
if not sheet.row_values(1):
    sheet.append_row(ENCABEZADOS)

# 3. Función de extracción y parseo detallado del portal del Senado
def extraer_detalle_senado(expediente):
    exp_str = str(expediente).strip()
    match = re.search(r'([a-zA-Z]+)\s*[\-\/]?\s*(\d+)\s*[\-\/]?\s*([\d\-]+)', exp_str)
    
    if not match:
        return None

    letra = match.group(1).upper()
    numero = match.group(2)
    periodo_raw = match.group(3)
    periodo = f"20{periodo_raw}" if len(periodo_raw) == 2 else periodo_raw

    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url_base = "https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx"

    try:
        resp_get = session.get(url_base, headers=headers, timeout=20)
        soup_get = BeautifulSoup(resp_get.text, 'html.parser')

        viewstate = soup_get.find("input", {"id": "__VIEWSTATE"})
        eventval = soup_get.find("input", {"id": "__EVENTVALIDATION"})

        payload = {
            "__VIEWSTATE": viewstate["value"] if viewstate else "",
            "__EVENTVALIDATION": eventval["value"] if eventval else "",
            "ctl00$ContentPlaceHolder1$ddlTipoP": letra,
            "ctl00$ContentPlaceHolder1$txtNumeroP": numero,
            "ctl00$ContentPlaceHolder1$ddlPeriodoP": periodo,
            "ctl00$ContentPlaceHolder1$btnBuscarP": "Buscar"
        }

        resp_post = session.post(url_base, data=payload, headers=headers, timeout=20)
        soup_post = BeautifulSoup(resp_post.text, 'html.parser')

        # Extraer campos de la vista detallada
        objeto = soup_post.find(id=re.compile(r'lblSumario|lblObjeto'))
        autor = soup_post.find(id=re.compile(r'lblAutor'))
        bloque = soup_post.find(id=re.compile(r'lblBloque'))
        comisiones_origen = soup_post.find(id=re.compile(r'lblComisionesOrigen'))
        estado_origen = soup_post.find(id=re.compile(r'lblEstadoOrigen|lblEstado'))
        comisiones_revisora = soup_post.find(id=re.compile(r'lblComisionesRevisora'))
        estado_revisora = soup_post.find(id=re.compile(r'lblEstadoRevisora'))
        media_sancion = "Sí" if "MEDIA SANCIÓN" in resp_post.text.upper() else "No"

        from datetime import datetime
        fecha_act = datetime.now().strftime("%Y-%m-%d %H:%M")

        return [
            exp_str,
            objeto.text.strip() if objeto else "No especificado",
            autor.text.strip() if autor else "Sin dato",
            bloque.text.strip() if bloque else "Sin dato",
            comisiones_origen.text.strip() if comisiones_origen else "Sin asignación",
            estado_origen.text.strip() if estado_origen else "En Estudio",
            comisiones_revisora.text.strip() if comisiones_revisora else "N/A",
            estado_revisora.text.strip() if estado_revisora else "N/A",
            media_sancion,
            fecha_act
        ]

    except Exception as err:
        print(f"❌ Error consultando {exp_str}: {err}")
        return None

# 4. Procesar lista de expedientes y volcar a Google Sheets
hoja_principal = sh.sheet1
expedientes = hoja_principal.col_values(1)[1:] # Asume expedientes en Columna A

filas_a_insertar = []
for exp in expedientes:
    if exp.strip():
        print(f"🔎 Procesando expediente: {exp}")
        datos_fila = extraer_detalle_senado(exp)
        if datos_fila:
            filas_a_insertar.append(datos_fila)

if filas_a_insertar:
    sheet.append_rows(filas_a_insertar)
    print(f"✔ Se insertaron {len(filas_a_insertar)} filas formateadas en 'Senado_PBA_Consolidado'.")

print("--- 🏁 PROCESO FINALIZADO ---")
