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
from collections import Counter, defaultdict

import pandas as pd

CHUNKSIZE = 200_000

# Variables binarias tipo SINAVE: 1 = Sí, 2 = No (97/98/99 = no aplica/se ignora/no especificado)
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


def encontrar_archivos():
    candidatos = []
    for base in (os.path.dirname(os.path.abspath(__file__)), os.path.expanduser("~/Downloads")):
        candidatos += glob.glob(os.path.join(base, "Dataframe_dengue_*confirmados*.csv"))
    # quitar duplicados preservando orden
    vistos = set()
    archivos = []
    for f in candidatos:
        if f not in vistos:
            vistos.add(f)
            archivos.append(f)
    return sorted(archivos)


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
    archivos = encontrar_archivos()
    print(f"Se encontraron {len(archivos)} archivos CSV.")
    if not archivos:
        print("No se encontraron archivos. Descárgalos del Release y colócalos junto a este script.")
        return

    filas_por_anio = Counter()
    conteo_entidad = Counter()
    # crosstab[comorbilidad][desenlace] = {"con_si": 0, "con_no": 0, "sin_si": 0, "sin_no": 0}
    crosstab = {c: {d: defaultdict(int) for d in DESENLACES} for c in COMORBILIDADES}
    correlaciones = {clima: {d: AcumuladorCorrelacion() for d in DESENLACES} for clima in VARIABLES_CLIMA}
    nulos = Counter()
    total_filas = 0

    for archivo in archivos:
        anio = extraer_anio(archivo)
        header = pd.read_csv(archivo, nrows=0).columns.tolist()
        cols_disponibles = [c for c in COLUMNAS_DESEADAS if c in header]
        print(f"Procesando {os.path.basename(archivo)} (año {anio}), columnas usadas: {len(cols_disponibles)}")

        for chunk in pd.read_csv(archivo, usecols=cols_disponibles, chunksize=CHUNKSIZE, low_memory=False):
            n = len(chunk)
            total_filas += n
            filas_por_anio[anio] += n

            for col in cols_disponibles:
                nulos[col] += chunk[col].isna().sum()

            if "Nombre_entidad" in chunk:
                conteo_entidad.update(chunk["Nombre_entidad"].dropna().value_counts().to_dict())

            for com in COMORBILIDADES:
                if com not in chunk:
                    continue
                for des in DESENLACES:
                    if des not in chunk:
                        continue
                    sub = chunk[[com, des]].dropna()
                    sub = sub[sub[com].isin([1, 2]) & sub[des].isin([1, 2])]
                    if sub.empty:
                        continue
                    ct = crosstab[com][des]
                    ct["con_si"] += ((sub[com] == 1) & (sub[des] == 1)).sum()
                    ct["con_no"] += ((sub[com] == 1) & (sub[des] == 2)).sum()
                    ct["sin_si"] += ((sub[com] == 2) & (sub[des] == 1)).sum()
                    ct["sin_no"] += ((sub[com] == 2) & (sub[des] == 2)).sum()

            for clima in VARIABLES_CLIMA:
                if clima not in chunk:
                    continue
                for des in DESENLACES:
                    if des not in chunk:
                        continue
                    sub = chunk[[clima, des]].dropna()
                    sub = sub[sub[des].isin([1, 2])]
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
        for des in DESENLACES:
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
        for des in DESENLACES:
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
