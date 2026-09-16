import gspread

# Indicar que use el archivo credentials.json de esta misma carpeta
gc = gspread.oauth(
    credentials_filename='credentials.json'
)

print("¡Autenticación completada con éxito!")