import os
import json
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

print("--- 🚀 INICIANDO BOT LEGISLATIVO PBA (VERSIÓN ROBUSTA DE EXTRACCIÓN) ---")

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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

# Palabras basura a descartar si el scraper las captura por error
TEXTOS_INVALIDOS = [
    "calle 51", "derechos reservados", "honorables senadores", 
    "desarrollado por", "términos y condiciones", "iniciar sesión",
    "cámara de senadores", "cámara de diputados"
]

def es_texto_valido(texto):
    if not texto or len(texto.strip()) < 15:
        return False
    txt_lower = texto.lower()
    for invalido in TEXTOS_INVALIDOS:
        if invalido in txt_lower and "ley" not in txt_lower and "declarando" not in txt_lower:
            return False
    return True

def consultar_expediente(expediente):
    exp_str = str(expediente).strip()
    match = re.search(r'([a-zA-Z]+)\s*[\-\/]?\s*(\d+)\s*[\-\/]?\s*([\d\-]+)', exp_str)
    
    if not match:
        print(f"⚠️ Formato no válido: '{exp_str}'")
        return None

    letra = match.group(1).upper()
    numero = match.group(2)
    periodo_raw = match.group(3)

    print(f"\n🔎 Buscando -> Letra: '{letra}', Nro: '{numero}', Período: '{periodo_raw}'")

    objeto, autor, estado = None, None, None

    # ESTRATEGIA 1: Búsqueda en el portal de la H. Cámara de Diputados de PBA
    try:
        url_hcd = f"https://www.hcdiputados-ba.gov.ar/proyectos_resultados.php?letra={letra}&numero={numero}&periodo={periodo_raw}"
        resp_hcd = session.get(url_hcd, headers=headers, timeout=10)
        soup_hcd = BeautifulSoup(resp_hcd.text, 'html.parser')

        for tr in soup_hcd.find_all("tr"):
            tds = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(tds) >= 2:
                candidato_obj = tds[1] if len(tds) > 1 else tds[0]
                if es_texto_valido(candidato_obj):
                    objeto = candidato_obj
                    autor = tds[2] if len(tds) > 2 else "Poder Ejecutivo"
                    estado = tds[3] if len(tds) > 3 else "En Tramitación"
                    break
    except Exception as e:
        print(f"   ⚠️ Fallo menor en consulta HCD: {e}")

    # ESTRATEGIA 2: Si no trajo resultados válidos de HCD, consultar el Senado
    if not objeto:
        try:
            url_senado = "https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx"
            resp_get = session.get(url_senado, headers=headers, timeout=10)
            soup_get = BeautifulSoup(resp_get.text, 'html.parser')

            vs = soup_get.find("input", {"id": "__VIEWSTATE"})
            ev = soup_get.find("input", {"id": "__EVENTVALIDATION"})

            p1 = periodo_raw.split("-")[0].strip()
            p1_full = f"20{p1}" if len(p1) == 2 else p1

            payload = {
                "__VIEWSTATE": vs["value"] if vs else "",
                "__EVENTVALIDATION": ev["value"] if ev else "",
                "ctl00$ContentPlaceHolder1$rdbTipoBusqueda": "Proyectos",
                "ctl00$ContentPlaceHolder1$ddlTipoP": "PE" if letra == "E" else letra,
                "ctl00$ContentPlaceHolder1$txtNumeroP": numero,
                "ctl00$ContentPlaceHolder1$ddlPeriodoP": p1_full,
                "ctl00$ContentPlaceHolder1$btnBuscarP": "Buscar"
            }

            resp_post = session.post(url_senado, data=payload, headers=headers, timeout=12)
            soup_post = BeautifulSoup(resp_post.text, 'html.parser')

            tabla = soup_post.find("table")
            if tabla:
                for tr in tabla.find_all("tr"):
                    tds = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                    if len(tds) >= 3:
                        candidato_obj = tds[1]
                        if es_texto_valido(candidato_obj):
                            objeto = candidato_obj
                            autor = tds[2] if len(tds) > 2 else "Poder Ejecutivo"
                            estado = tds[-1] if len(tds) > 3 else "En Estudio"
                            break
        except Exception as e:
            print(f"   ⚠️ Fallo menor en consulta Senado: {e}")

    if not objeto:
        print(f"   ⚠️ No se encontraron datos válidos para {exp_str}.")
        return None

    objeto_clean = re.sub(r'\s+', ' ', objeto)[:250]
    autor_clean = autor if autor else ("Poder Ejecutivo PBA" if letra in ["E", "PE"] else "Sin datos")
    bloque = "Poder Ejecutivo PBA" if letra in ["E", "PE"] else "Sin datos"
    com_origen = "Asuntos Constitucionales / Legislación General"
    est_origen = estado if estado else "En Tramitación"
    com_revisora = "N/A"
    est_revisora = "N/A"
    media_sancion = "No"
    fecha_act = datetime.now().strftime("%d/%m/%Y %H:%M")

    print(f"   ✔ ¡DATOS ENCONTRADOS!: '{objeto_clean[:60]}...' | Estado: '{est_origen}'")

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

# 3. Bucle principal con protección contra caídas masivas
sheet_origen = sh.sheet1
expedientes_origen = sheet_origen.col_values(1)[1:]

cont_agregados = 0

for exp in expedientes_origen:
    if exp.strip():
        try:
            datos = consultar_expediente(exp)
            if datos:
                sheet_consolidado.append_row(datos)
                cont_agregados += 1
                print("   💾 Fila guardada exitosamente en Google Sheets.")
        except Exception as err_fila:
            print(f"   ❌ Error al procesar la fila '{exp}': {err_fila}. Continuando con el siguiente...")

print(f"\n🎉 Proceso finalizado. Total guardados: {cont_agregados}")
