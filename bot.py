def main():
    print("Iniciando monitoreo del Senado PBA...")
    hoja = autenticar_google_sheets()
    
    # 1. Obtener todos los registros
    filas = hoja.get_all_records()
    print(f"Total de filas leídas: {len(filas)}")

    # 2. Detectar dinámicamente la columna 'ESTADO EN COMISIÓN CÁMARA DE ORIGEN' o similar
    encabezados = hoja.row_values(1)
    print("Encabezados encontrados:", encabezados)
    
    col_estado_num = None
    for i, h in enumerate(encabezados, start=1):
        if "ESTADO" in h.upper() and "ORIGEN" in h.upper():
            col_estado_num = i
            break
    
    if not col_estado_num:
        # Fallback a columna F (6)
        col_estado_num = 6
    
    print(f"Escribiendo cambios en la columna número: {col_estado_num}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for idx, fila in enumerate(filas, start=2): # Comienza en fila 2 por encabezados
            expediente = fila.get("EXPEDIENTE LEGISLATIVO") or fila.get("Expediente")
            estado_actual = fila.get("ESTADO EN COMISIÓN CÁMARA DE ORIGEN") or fila.get("Estado Guardado") or ""

            if not expediente:
                continue

            print(f"\n--- [Fila {idx}] Expediente: {expediente} ---")
            print(f"Estado en Sheet: '{estado_actual}'")
            
            nuevo_estado = consultar_estado_senado(page, expediente)
            print(f"Estado en Web:   '{nuevo_estado}'")

            if nuevo_estado:
                if str(nuevo_estado).strip().lower() != str(estado_actual).strip().lower():
                    print(f"🚨 ¡CAMBIO DETECTADO! Actualizando Fila {idx}, Columna {col_estado_num}...")
                    hoja.update_cell(idx, col_estado_num, nuevo_estado)
                    print("✅ Celda actualizada correctamente en Google Sheets.")
                else:
                    print("ℹ️ El estado web es idéntico al guardado en la planilla. Sin cambios.")
            else:
                print("⚠️ No se pudo extraer el estado desde la web para este expediente.")

        browser.close()
