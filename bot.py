import os
import json
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

print("--- 🚀 INICIANDO BOT DE MONITOREO LEGISLATIVO PBA (SENADO + DIPUTADOS) ---")

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

session = requests.Session()
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def consultar_expediente(expediente):
    exp_str = str(expediente).strip()
    match = re.search(r'([a-zA-Z]+)\s*[\-\/]?\s*(\d+)\s*[\-\/]?\s*([\d\-]+)', exp_str)
    
    if not match:
        print(f"⚠️ Formato no válido: '{exp_str}'")
        return None

    letra = match.group(1).upper()
    numero = match.group(2)
    periodo_raw = match.group(3)

    p1 = periodo_raw.split("-")[0].strip()
    p1_full = f"20{p1}" if len(p1) == 2 else p1

    print(f"\n🔎 Buscando -> Letra: '{letra}', Nro: '{numero}', Período: '{periodo_raw}'")

    objeto, autor, comision, estado = None, None, None, None

    # ESTRATEGIA A: Si es letra E o D, consultar portal de la H. Cámara de Diputados
    if letra in ["E", "D"]:
        try:
            url_dip = f"https://www me.hcdiputados-ba.gov.ar/proyectos/ver_proyecto.php?exp={letra}-{numero}/{periodo_raw}"
            # Petición a la búsqueda de la HCD
            url_busqueda = "https://www.hcdiputados-ba.gov.ar/index.php"
            resp = session.get(f"https://intranet.hcdiputados-ba.gov.ar/proyectos/{p1}-{len(p1)}E{numero}0102025-07-0110-08-25.pdf", headers=headers, timeout=10)
            
            # Buscar metadatos en repositorio abierto de HCD
            url_api = f"https://www.hcdiputados-ba.gov.ar/proyectos_resultados.php?letra={letra}&numero={numero}&anio={p1_full}"
            r_dip = session.get(url_api, headers=headers, timeout=10)
            soup_dip = BeautifulSoup(r_dip.text, 'html.parser')

            for tr in soup_dip.find_all("tr"):
                txt = tr.get_text(strip=True)
                if numero in txt:
                    tds = [td.get_text(strip=True) for td in tr.find_all("td")]
                    if len(tds) >= 3:
                        objeto = tds[1]
                        autor = tds[2] if len(tds) > 2 else "Poder Ejecutivo / Diputados"
                        estado = tds[3] if len(tds) > 3 else "En Tramitación"
        except Exception as ex:
            pass

    # ESTRATEGIA B: Si no trajo datos o es letra F / PE, consultar portal del Senado
    if not objeto:
        try:
            url_senado = "https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx"
            resp_get = session.get(url_senado, headers=headers, timeout=15)
            soup_get = BeautifulSoup(resp_get.text, 'html.parser')

            vs = soup_get.find("input", {"id": "__VIEWSTATE"})
            ev = soup_get.find("input", {"id": "__EVENTVALIDATION"})

            # Mapeo de letra para el Senado (E suele ingresar como PE o E-E)
            letra_senado = "PE" if letra == "E" else letra

            payload = {
                "__VIEWSTATE": vs["value"] if vs else "",
                "__EVENTVALIDATION": ev["value"] if ev else "",
                "ctl00$ContentPlaceHolder1$rdbTipoBusqueda": "Proyectos",
                "ctl00$ContentPlaceHolder1$ddlTipoP": letra_senado,
                "ctl00$ContentPlaceHolder1$txtNumeroP": numero,
                "ctl00$ContentPlaceHolder1$ddlPeriodoP": p1_full,
                "ctl00$ContentPlaceHolder1$btnBuscarP": "Buscar"
            }

            resp_post = session.post(url_senado, data=payload, headers=headers, timeout=20)
            soup_post = BeautifulSoup(resp_post.text, 'html.parser')

            tabla = soup_post.find("table")
            if tabla:
                for tr in tabla.find_all("tr"):
                    txt = tr.get_text(strip=True)
                    if numero in txt and "Calle 51" not in txt:
                        tds = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                        if len(tds) >= 2:
                            objeto = tds[1]
                            autor = tds[2] if len(tds) > 2 else "Sin datos"
                            estado = tds[-1] if len(tds) > 3 else "En Estudio"
        except Exception as ex:
            pass

    if not objeto:
        print(f"   ⚠️ No se encontraron resultados en ningún portal para {exp_str}.")
        return None

    objeto = objeto if objeto else "Proyecto de Ley / Decreto"
    autor = autor if autor else "Gobernación / Poder Ejecutivo"
    bloque = "Poder Ejecutivo PBA" if letra == "E" else "Sin datos"
    com_origen = comision if comision else "Asuntos Constitucionales / Legislación General"
    est_origen = estado if estado else "En Estudio"
    com_revisora = "N/A"
    est_revisora = "N/A"
    media_sancion = "No"
    fecha_act = datetime.now().strftime("%d/%m/%Y %H:%M")

    print(f"   ✔ ¡DATOS ENCONTRADOS!: '{objeto[:50]}...' | Estado: '{est_origen}'")

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
