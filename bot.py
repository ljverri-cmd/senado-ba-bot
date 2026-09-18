import os
import json
import re
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

print("--- 🚀 INICIANDO BOT COM SUBMISSÃO DIRETA SENADO PBA ---")

# 1. Autenticação e conexão com o Google Sheets
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

    print(f"✔ Conectado com sucesso à planilha: '{sh.title}'")
except Exception as e:
    print(f"❌ Erro al conectar com Google Sheets: {e}")
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

# 2. Extração adaptada com submissão direta do formulário
def extraer_datos_expediente(page, expediente):
    exp_str = str(expediente).strip()
    match = re.search(r'([a-zA-Z]+)\s*[\-\/]?\s*(\d+)\s*[\-\/]?\s*([\d\-]+)', exp_str)
    
    if not match:
        print(f"⚠️ Formato de expediente inválido: '{exp_str}'")
        return None

    letra = match.group(1).upper()
    numero = match.group(2)
    periodo_raw = match.group(3)

    if "-" in periodo_raw and len(periodo_raw) == 5:
        p1, p2 = periodo_raw.split("-")
        periodo = f"20{p1}-20{p2}"
    else:
        periodo = periodo_raw

    print(f"\n🔎 Consultando expediente: {exp_str} -> Tipo: '{letra}', Nro: '{numero}', Período: '{periodo}'")

    try:
        page.goto("https://legislativa.senado-ba.gov.ar/Leyes_y_proyectos.aspx", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)

        selector_tipo = "select[id*='ddlTipo'], select[name*='ddlTipo']"
        selector_numero = "input[id*='txtNumero']:visible, input[name*='txtNumero']:visible"
        selector_periodo = "select[id*='ddlPeriodo'], select[name*='ddlPeriodo']"

        page.wait_for_selector(selector_numero, state="visible", timeout=15000)

        # Selecionar Tipo / Letra
        try:
            page.locator(selector_tipo).first.select_option(value=letra)
        except Exception:
            try:
                page.locator(selector_tipo).first.select_option(label=letra)
            except Exception:
                pass

        # Preencher o número
        page.locator(selector_numero).first.fill(numero)

        # Selecionar o Período
        if page.locator(selector_periodo).count() > 0:
            try:
                page.locator(selector_periodo).first.select_option(label=periodo)
            except Exception:
                try:
                    page.locator(selector_periodo).first.select_option(value=periodo)
                except Exception:
                    pass

        # Submeter formulário via JavaScript ou através de clique genérico
        try:
            btn = page.locator("a[id*='btnBuscar'], input[id*='btnBuscar'], button[id*='btnBuscar'], .btn-buscar").first
            if btn.is_visible():
                btn.click()
            else:
                page.locator(selector_numero).first.press("Enter")
        except Exception:
            page.locator(selector_numero).first.press("Enter")

        # Aguardar processamento da resposta AJAX
        page.wait_for_timeout(4000)

        html_page = page.content()

        if "No se encontraron registros" in html_page or "Sin resultados" in html_page:
            print("   ⚠️ Nenhum resultado encontrado para este expediente.")
            return None

        # Leitura das informações retornadas na página
        objeto = page.locator("[id*='lblObjeto'], [id*='lblSumario'], [id*='Caratula'], .caratula").first.text_content() if page.locator("[id*='lblObjeto'], [id*='lblSumario'], [id*='Caratula'], .caratula").count() > 0 else "Sin datos"
        autor = page.locator("[id*='lblAutor']").first.text_content() if page.locator("[id*='lblAutor']").count() > 0 else "Sin datos"
        bloque = page.locator("[id*='lblBloque']").first.text_content() if page.locator("[id*='lblBloque']").count() > 0 else "Sin datos"
        
        com_origen = page.locator("[id*='lblComisionesOrigen']").first.text_content() if page.locator("[id*='lblComisionesOrigen']").count() > 0 else "Sin asignación"
        est_origen = page.locator("[id*='lblEstadoOrigen'], [id*='lblEstado']").first.text_content() if page.locator("[id*='lblEstadoOrigen'], [id*='lblEstado']").count() > 0 else "En Estudio"
        
        com_revisora = page.locator("[id*='lblComisionesRevisora']").first.text_content() if page.locator("[id*='lblComisionesRevisora']").count() > 0 else "N/A"
        est_revisora = page.locator("[id*='lblEstadoRevisora']").first.text_content() if page.locator("[id*='lblEstadoRevisora']").count() > 0 else "N/A"

        media_sancion = "Sí" if "MEDIA SANCIÓN" in html_page.upper() else "No"
        fecha_act = datetime.now().strftime("%d/%m/%Y %H:%M")

        print("   ✔ Dados extraídos com sucesso!")

        return [
            exp_str,
            objeto.strip() if objeto else "Sin datos",
            autor.strip() if autor else "Sin datos",
            bloque.strip() if bloque else "Sin datos",
            com_origen.strip() if com_origen else "Sin asignación",
            est_origen.strip() if est_origen else "En Estudio",
            com_revisora.strip() if com_revisora else "N/A",
            est_revisora.strip() if est_revisora else "N/A",
            media_sancion,
            fecha_act
        ]

    except Exception as e:
        print(f"   ❌ Erro ao processar {exp_str}: {e}")
        return None

# 3. Leitura e atualização da planilha
sheet_origen = sh.sheet1
expedientes_origen = sheet_origen.col_values(1)[1:]

filas_para_consolidado = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    page = context.new_page()

    for exp in expedientes_origen:
        if exp.strip():
            datos = extraer_datos_expediente(page, exp)
            if datos:
                filas_para_consolidado.append(datos)

    browser.close()

if filas_para_consolidado:
    sheet_consolidado.append_rows(filas_para_consolidado)
    print(f"\n🎉 Processo concluído! {len(filas_para_consolidado)} registros adicionados em 'Senado_PBA_Consolidado'.")
else:
    print("\n⚠️ Nenhum registro novo obtido.")
