import os
import json
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

print("--- 🚀 INICIANDO BOT SENADO PBA (HTTP DIRECCIÓN DIRECTA) ---")

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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}

# 2. Función de consulta y extracción
def extraer_datos_expediente(session, expediente):
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
        # Petición GET directa con parámetros de búsqueda
        url = f"https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx?tipo={letra}&numero={numero}&periodo={periodo}"
        resp = session.get(url, headers=headers, timeout=20)

        if resp.status_code != 200:
            print(f"   ⚠️ Error HTTP {resp.status_code} al consultar la página.")
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        texto_pagina = soup.get_text(separator="\n")

        if "No se encontraron" in texto_pagina or "Sin resultados" in texto_pagina:
            print("   ⚠️ No se encontraron resultados para este expediente.")
            return None

        # Búsqueda por Regex en el texto estructurado del HTML
        def buscar_campo(patrones):
            for pat in patrones:
                m = re.search(f"{pat}[:\\s]+([^\\n\\r]+)", texto_pagina, re.IGNORECASE)
                if m:
                    val = m.group(1).strip()
                    if val and len(val) > 1 and "SIN DATOS" not in val.upper():
                        return val
            return None

        objeto = buscar_campo(["Objeto", "Sumario", "Carátula", "Extracto", "Proyecto"])
        autor = buscar_campo(["Autor", "Iniciador", "Firmante", "Senador"])
        bloque = buscar_campo(["Bloque", "Partido", "Bloque Político"])
        com_origen = buscar_campo(["Comisión", "Comisiones", "Giro a comisión"])
        est_origen = buscar_campo(["Estado", "Estado en comisión", "Situación"])

        # Si BeautifulSoup encuentra tablas de datos (Grid)
        tablas = soup.find_all("table")
        for tabla in tablas:
            filas = tabla.find_all("tr")
            if len(filas) > 1:
                celdas = filas[1].find_all(["td", "th"])
                txt_celdas = [c.get_text(strip=True) for c in celdas]
                if len(txt_celdas) >= 3:
                    if not objeto or objeto == "Ver ficha en la web":
                        objeto = txt_celdas[1] if len(txt_celdas[1]) > 5 else objeto
                    if not autor or autor == "Sin datos":
                        autor = txt_celdas[2] if len(txt_celdas[2]) > 2 else autor

        # Valores por defecto de resguardo
        objeto = objeto if objeto else "Proyecto registrado en portal"
        autor = autor if autor else "Sin datos"
        bloque = bloque if bloque else "Sin datos"
        com_origen = com_origen if com_origen else "Sin asignación"
        est_origen = est_origen if est_origen else "En Estudio"

        com_revisora = "N/A"
        est_revisora = "N/A"
        media_sancion = "Sí" if "MEDIA SANCIÓN" in texto_pagina.upper() else "No"
        fecha_act = datetime.now().strftime("%d/%m/%Y %H:%M")

        print(f"   ✔ Extraído correctamente: Objeto='{objeto[:40]}...', Autor='{autor}'")

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

# 3. Bucle principal
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

print(f"\n🎉 ¡Proceso finalizado! Se actualizaron {cont_agregados} expedientes.")
