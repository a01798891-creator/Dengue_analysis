import pandas as pd
import glob
import os

def main():
    # Definir la ruta de los archivos (usando comodines para abarcar los años 20 al 26)
    ruta = r'C:\Users\rzahi\Downloads\Dataframe_dengue_*_confirmados_*.csv'
    archivos_csv = glob.glob(ruta)
    
    print(f"Se encontraron {len(archivos_csv)} archivos CSV.")
    if not archivos_csv:
        print("No se encontraron archivos para analizar.")
        return

    # Para el análisis descriptivo y obtener las variables, leeremos el primer archivo
    archivo_muestra = archivos_csv[0]
    print(f"\nAnalizando el archivo de muestra: {os.path.basename(archivo_muestra)}")
    
    # Leer solo las primeras 100 filas para agilizar la identificación de columnas
    df = pd.read_csv(archivo_muestra, nrows=100)
    
    # Separar variables por tipo de dato
    # Consideramos numéricas a las float64 e int64, y categóricas al resto (object, bool, etc.)
    # Nota: A veces variables codificadas como enteros (ej. SEXO=1,2) son categóricas.
    variables_numericas = df.select_dtypes(include=['int64', 'float64']).columns.tolist()
    variables_categoricas = df.select_dtypes(exclude=['int64', 'float64']).columns.tolist()

    print("\n--- Variables Numéricas Detectadas ---")
    for var in variables_numericas:
        print(f" - {var}")

    print("\n--- Variables Categóricas Detectadas ---")
    for var in variables_categoricas:
        print(f" - {var}")

    print("\n" + "="*60)
    print("PREGUNTA DE INVESTIGACIÓN SUGERIDA:")
    print("="*60)
    print("Al observar que los datos contienen información sobre comorbilidades (DIABETES, HIPERTENSION, etc.),")
    print("datos demográficos (EDAD_ANOS, SEXO), variables meteorológicas (temperatura, precipitación, humedad) ")
    print("y gravedad del dengue (HEMORRAGICOS, ESTATUS_CASO, DEFUNCION), una posible pregunta de investigación es:\n")
    print("¿Cómo influyen las variables meteorológicas (temperatura, precipitación) y las comorbilidades ")
    print("preexistentes (diabetes, hipertensión) en la probabilidad de desarrollar dengue hemorrágico o ")
    print("resultar en defunción en las distintas zonas geográficas de México entre 2020 y 2026?\n")
    
if __name__ == "__main__":
    main()
