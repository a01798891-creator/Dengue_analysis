"""
Recorre los CSV de dengue (por chunks, para no cargar los archivos de cientos de MB
en memoria) y calcula estadísticas descriptivas, tasas y correlaciones que sirven
como insumo para proponer una pregunta de investigación basada en datos reales,
en vez de una pregunta fija de antemano.

Uso: coloca los CSV descargados del Release en la carpeta del proyecto (o en
Downloads, como usa analisis_dengue.py) y corre:
    python generar_insights.py
"""

import glob
import os
import re
import time
from collections import Counter, defaultdict

import pandas as pd

CHUNKSIZE = 200_000
ARCHIVO_DESCRIPTORES = "Descriptores_Dengue.xlsx"
ARCHIVO_CATALOGOS = "Catalogos_Dengue.xlsx"

COMORBILIDADES = [
    "DIABETES", "HIPERTENSION", "ENFERMEDAD_ULC_PEPTICA",
    "ENFERMEDAD_RENAL", "INMUNOSUPR", "CIRROSIS_HEPATICA", "EMBARAZO",
]
DESENLACES = ["DEFUNCION", "HEMORRAGICOS"]
VARIABLES_CLIMA = ["temperatura", "prec", "humedad_relativa", "evap"]
COLUMNAS_DESEADAS = (
    ["EDAD_ANOS", "SEXO", "TIPO_PACIENTE", "Nombre_entidad"]
    + COMORBILIDADES + DESENLACES + VARIABLES_CLIMA
)


def cargar_catalogos(directorio):
    """Lee Descriptores_Dengue.xlsx y Catalogos_Dengue.xlsx si existen, para no
    asumir a ciegas qué significa cada código (p.ej. si 1=SI o 1=NO)."""
    descriptores = {}
    ruta_desc = os.path.join(directorio, ARCHIVO_DESCRIPTORES)
    if os.path.exists(ruta_desc):
        try:
            df = pd.read_excel(ruta_desc, sheet_name="DESCRIPTORES")
            df.columns = [str(c).strip().upper() for c in df.columns]
            col_nombre = next(c for c in df.columns if "NOMBRE" in c)
            col_desc = next(c for c in df.columns if "DESCRIPCION" in c or "DESCRIPCIÓN" in c)
            for _, fila in df.iterrows():
                nombre = str(fila[col_nombre]).strip().replace(" ", "_")
                descriptores[nombre] = str(fila[col_desc]).strip()
        except Exception as e:
            print(f"  Aviso: no se pudo leer {ARCHIVO_DESCRIPTORES}: {e}")

    # códigos SI/NO y TIPO_PACIENTE, con default por si el catálogo no está disponible
    codigo_si, codigo_no = 1, 2
    codigo_ambulatorio, codigo_hospitalizado = 1, 2
    ruta_cat = os.path.join(directorio, ARCHIVO_CATALOGOS)
    if os.path.exists(ruta_cat):
        try:
            xls = pd.ExcelFile(ruta_cat)
            hoja_si_no = next(h for h in xls.sheet_names if "SI_NO" in h.upper().replace(" ", "_"))
            cat = pd.read_excel(xls, sheet_name=hoja_si_no)
            cat.columns = [str(c).strip().upper() for c in cat.columns]
            col_clave = next(c for c in cat.columns if "CLAVE" in c)
            col_desc = next(c for c in cat.columns if "DESCRIP" in c)
            for _, fila in cat.iterrows():
                etiqueta = str(fila[col_desc]).strip().upper()
                if etiqueta == "SI":
                    codigo_si = int(fila[col_clave])
                elif etiqueta == "NO":
                    codigo_no = int(fila[col_clave])

            hoja_tp = next((h for h in xls.sheet_names if "TIPO_PACIENTE" in h.upper().replace(" ", "_")), None)
            if hoja_tp:
                cat_tp = pd.read_excel(xls, sheet_name=hoja_tp)
                cat_tp.columns = [str(c).strip().upper() for c in cat_tp.columns]
                col_clave_tp = next(c for c in cat_tp.columns if "CLAVE" in c)
                col_desc_tp = next(c for c in cat_tp.columns if "DESCRIP" in c)
                for _, fila in cat_tp.iterrows():
                    etiqueta = str(fila[col_desc_tp]).strip().upper()
                    if etiqueta == "AMBULATORIO":
                        codigo_ambulatorio = int(fila[col_clave_tp])
                    elif etiqueta == "HOSPITALIZADO":
                        codigo_hospitalizado = int(fila[col_clave_tp])
        except Exception as e:
            print(f"  Aviso: no se pudo leer {ARCHIVO_CATALOGOS}: {e}")

    return {
        "descriptores": descriptores,
        "si": codigo_si,
        "no": codigo_no,
        "ambulatorio": codigo_ambulatorio,
        "hospitalizado": codigo_hospitalizado,
    }


def encontrar_archivos():
    # Si el mismo nombre existe en varias carpetas (p.ej. proyecto y Downloads),
    # se usa solo una copia para no contar los mismos casos dos veces.
    elegidos = {}
    for base in (os.path.dirname(os.path.abspath(__file__)), os.path.expanduser("~/Downloads")):
        for ruta in glob.glob(os.path.join(base, "Dataframe_dengue_*confirmados*.csv")):
            elegidos.setdefault(os.path.basename(ruta), ruta)
    return sorted(elegidos.values())


def extraer_anio(nombre_archivo):
    m = re.search(r"dengue_(\d+)_", os.path.basename(nombre_archivo))
    if not m:
        return None
    n = int(m.group(1))
    return 2000 + n if n < 100 else n


class AcumuladorCorrelacion:
    """Pearson en línea: acumula sumas para no guardar los datos completos en memoria."""

    def __init__(self):
        self.n = 0
        self.sx = self.sy = self.sxy = self.sx2 = self.sy2 = 0.0

    def actualizar(self, x, y):
        n = len(x)
        if n == 0:
            return
        self.n += n
        self.sx += x.sum()
        self.sy += y.sum()
        self.sxy += (x * y).sum()
        self.sx2 += (x ** 2).sum()
        self.sy2 += (y ** 2).sum()

    def r(self):
        if self.n < 2:
            return None
        num = self.n * self.sxy - self.sx * self.sy
        den = ((self.n * self.sx2 - self.sx ** 2) * (self.n * self.sy2 - self.sy ** 2)) ** 0.5
        if den == 0:
            return None
        return num / den


def main():
    directorio = os.path.dirname(os.path.abspath(__file__))
    catalogo = cargar_catalogos(directorio)
    codigo_si, codigo_no = catalogo["si"], catalogo["no"]
    codigo_hosp = catalogo["hospitalizado"]

    print(f"Códigos detectados en el catálogo: SI={codigo_si}, NO={codigo_no}, HOSPITALIZADO={codigo_hosp}")

    if catalogo["descriptores"]:
        print("\n" + "=" * 70)
        print("DICCIONARIO DE VARIABLES (de Descriptores_Dengue.xlsx)")
        print("=" * 70)
        for var in COMORBILIDADES + DESENLACES + ["TIPO_PACIENTE", "SEXO", "EDAD_ANOS"]:
            desc = catalogo["descriptores"].get(var)
            if desc:
                print(f"  {var}: {desc}")

    # DESENLACES_EXTENDIDO incluye HOSPITALIZADO (derivado de TIPO_PACIENTE) como
    # proxy adicional de severidad, además de DEFUNCION y HEMORRAGICOS.
    desenlaces_ext = DESENLACES + ["HOSPITALIZADO"]

    archivos = encontrar_archivos()
    print(f"\nSe encontraron {len(archivos)} archivos CSV.")
    if not archivos:
        print("No se encontraron archivos. Descárgalos del Release y colócalos junto a este script.")
        return

    filas_por_anio = Counter()
    conteo_entidad = Counter()
    # crosstab[comorbilidad][desenlace] = {"con_si": 0, "con_no": 0, "sin_si": 0, "sin_no": 0}
    crosstab = {c: {d: defaultdict(int) for d in desenlaces_ext} for c in COMORBILIDADES}
    correlaciones = {clima: {d: AcumuladorCorrelacion() for d in desenlaces_ext} for clima in VARIABLES_CLIMA}
    nulos = Counter()
    total_filas = 0

    for archivo in archivos:
        anio = extraer_anio(archivo)
        header = pd.read_csv(archivo, nrows=0).columns.tolist()
        cols_disponibles = [c for c in COLUMNAS_DESEADAS if c in header]
        tam_mb = os.path.getsize(archivo) / (1024 * 1024)
        print(f"Procesando {os.path.basename(archivo)} (año {anio}, {tam_mb:.0f} MB), columnas usadas: {len(cols_disponibles)}")

        inicio = time.time()
        filas_archivo = 0
        for i, chunk in enumerate(pd.read_csv(archivo, usecols=cols_disponibles, chunksize=CHUNKSIZE, low_memory=False), start=1):
            n = len(chunk)
            total_filas += n
            filas_por_anio[anio] += n
            filas_archivo += n
            if i % 5 == 0:
                print(f"  ...{filas_archivo:,} filas leídas ({time.time() - inicio:.0f}s)", flush=True)

            for col in cols_disponibles:
                nulos[col] += chunk[col].isna().sum()

            if "Nombre_entidad" in chunk:
                conteo_entidad.update(chunk["Nombre_entidad"].dropna().value_counts().to_dict())

            # HOSPITALIZADO se deriva de TIPO_PACIENTE, recodificado a la misma
            # escala SI/NO del catálogo para poder reusar la misma lógica de abajo.
            if "TIPO_PACIENTE" in chunk:
                chunk = chunk.copy()
                chunk["HOSPITALIZADO"] = chunk["TIPO_PACIENTE"].map(
                    {codigo_hosp: codigo_si, catalogo["ambulatorio"]: codigo_no}
                )

            for com in COMORBILIDADES:
                if com not in chunk:
                    continue
                for des in desenlaces_ext:
                    if des not in chunk:
                        continue
                    sub = chunk[[com, des]].dropna()
                    sub = sub[sub[com].isin([codigo_si, codigo_no]) & sub[des].isin([codigo_si, codigo_no])]
                    if sub.empty:
                        continue
                    ct = crosstab[com][des]
                    ct["con_si"] += ((sub[com] == codigo_si) & (sub[des] == codigo_si)).sum()
                    ct["con_no"] += ((sub[com] == codigo_si) & (sub[des] == codigo_no)).sum()
                    ct["sin_si"] += ((sub[com] == codigo_no) & (sub[des] == codigo_si)).sum()
                    ct["sin_no"] += ((sub[com] == codigo_no) & (sub[des] == codigo_no)).sum()

            for clima in VARIABLES_CLIMA:
                if clima not in chunk:
                    continue
                for des in desenlaces_ext:
                    if des not in chunk:
                        continue
                    sub = chunk[[clima, des]].dropna()
                    sub = sub[sub[des].isin([codigo_si, codigo_no])]
                    if sub.empty:
                        continue
                    correlaciones[clima][des].actualizar(sub[clima].astype(float), sub[des].astype(float))

    # ---------- Reporte ----------
    print("\n" + "=" * 70)
    print("RESUMEN DE DATOS")
    print("=" * 70)
    print(f"Total de registros procesados: {total_filas:,}")
    for anio in sorted(k for k in filas_por_anio if k is not None):
        print(f"  {anio}: {filas_por_anio[anio]:,} casos")

    print("\n--- Top 10 entidades con más casos ---")
    for entidad, n in conteo_entidad.most_common(10):
        print(f"  {entidad}: {n:,}")

    print("\n--- % de valores nulos por variable (sobre filas leídas) ---")
    for col, n in sorted(nulos.items(), key=lambda kv: -kv[1]):
        if n > 0:
            print(f"  {col}: {100 * n / total_filas:.1f}%")

    print("\n" + "=" * 70)
    print("TASAS DE DESENLACE SEGÚN COMORBILIDAD (riesgo relativo aproximado)")
    print("=" * 70)
    hallazgos_comorbilidad = []
    for com in COMORBILIDADES:
        for des in desenlaces_ext:
            ct = crosstab[com][des]
            con_total = ct["con_si"] + ct["con_no"]
            sin_total = ct["sin_si"] + ct["sin_no"]
            if con_total < 30 or sin_total < 30:
                continue
            tasa_con = ct["con_si"] / con_total
            tasa_sin = ct["sin_si"] / sin_total
            if tasa_sin == 0:
                continue
            rr = tasa_con / tasa_sin
            print(f"  {com} -> {des}: tasa con={tasa_con*100:.2f}% vs sin={tasa_sin*100:.2f}%  (riesgo relativo x{rr:.2f}, n={con_total+sin_total:,})")
            hallazgos_comorbilidad.append((com, des, rr, con_total + sin_total))

    print("\n" + "=" * 70)
    print("CORRELACIÓN ENTRE VARIABLES CLIMÁTICAS Y DESENLACES")
    print("=" * 70)
    hallazgos_clima = []
    for clima in VARIABLES_CLIMA:
        for des in desenlaces_ext:
            r = correlaciones[clima][des].r()
            n = correlaciones[clima][des].n
            if r is None or n < 30:
                continue
            print(f"  {clima} vs {des}: r={r:.3f} (n={n:,})")
            hallazgos_clima.append((clima, des, r, n))

    # ---------- Insights dinámicos ----------
    print("\n" + "=" * 70)
    print("POSIBLES INSIGHTS")
    print("=" * 70)

    insights = []
    if hallazgos_comorbilidad:
        top_com = max(hallazgos_comorbilidad, key=lambda h: abs(h[2] - 1))
        insights.append(
            f"- {top_com[0]} se asocia con el mayor cambio de riesgo de {top_com[1]} "
            f"(riesgo relativo x{top_com[2]:.2f}, basado en {top_com[3]:,} casos con dato válido)."
        )
    if hallazgos_clima:
        top_clima = max(hallazgos_clima, key=lambda h: abs(h[2]))
        fuerza = "fuerte" if abs(top_clima[2]) > 0.3 else "débil a moderada"
        insights.append(
            f"- La variable climática con correlación más notable es {top_clima[0]} respecto a "
            f"{top_clima[1]} (r={top_clima[2]:.3f}, {fuerza})."
        )
    if len(filas_por_anio) > 1:
        anios_validos = sorted(k for k in filas_por_anio if k is not None)
        primero, ultimo = anios_validos[0], anios_validos[-1]
        cambio = filas_por_anio[ultimo] - filas_por_anio[primero]
        tendencia = "aumentó" if cambio > 0 else "disminuyó"
        insights.append(
            f"- El número de casos confirmados {tendencia} de {filas_por_anio[primero]:,} en {primero} "
            f"a {filas_por_anio[ultimo]:,} en {ultimo}."
        )
    if conteo_entidad:
        entidad_top, n_top = conteo_entidad.most_common(1)[0]
        insights.append(f"- {entidad_top} concentra el mayor número de casos confirmados ({n_top:,}).")

    for i in insights:
        print(i)

    print("\n" + "=" * 70)
    print("PREGUNTA DE INVESTIGACIÓN SUGERIDA (basada en lo anterior)")
    print("=" * 70)
    if hallazgos_comorbilidad and hallazgos_clima:
        com, des_com, rr, _ = max(hallazgos_comorbilidad, key=lambda h: abs(h[2] - 1))
        clima, des_clima, r, _ = max(hallazgos_clima, key=lambda h: abs(h[2]))
        anios_validos = sorted(k for k in filas_por_anio if k is not None)
        rango_anios = f"{anios_validos[0]}-{anios_validos[-1]}" if anios_validos else "el periodo analizado"
        print(
            f"¿En qué medida {com.lower()} como comorbilidad (riesgo relativo observado x{rr:.2f} sobre "
            f"{des_com.lower()}) y {clima} (r={r:.3f} con {des_clima.lower()}) interactúan para explicar la "
            f"severidad del dengue en las entidades con mayor incidencia de México durante {rango_anios}?"
        )
    else:
        print("No hubo suficientes datos válidos para sugerir automáticamente una pregunta; revisa los hallazgos de arriba.")


if __name__ == "__main__":
    main()
