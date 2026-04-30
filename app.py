from flask import Flask, render_template, request, redirect, session, send_file
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import psycopg2

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "clave_super_segura_123")

ARCHIVO = "inventario.xlsx"
DATABASE_URL = os.environ.get("DATABASE_URL")

USUARIOS = {
    "PC1": "123",
    "PC2": "123",
    "PC3": "123"
}

def get_conn():
    if not DATABASE_URL:
        return None
    try:
        return psycopg2.connect(DATABASE_URL)
    except:
        return None


def init_db():
    conn = get_conn()
    if not conn:
        return

    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ventas (
            id SERIAL PRIMARY KEY,
            usuario TEXT,
            codigo TEXT,
            nombre TEXT,
            cantidad INT,
            subtotal FLOAT,
            metodo TEXT,
            fecha TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


def limpiar(valor):
    return str(valor).strip().upper() if valor else ""


def login_requerido():
    return "user" not in session


def hora_peru():
    return datetime.now(ZoneInfo("America/Lima")).replace(tzinfo=None)


def cargar_excel():
    columnas = [
        "CODIGO","NOMBRE DEL PRODUCTO","EDITORIAL","CATEGORIA",
        "COMPRAS","VENTAS","STOCK","COSTO UNITARIO",
        "PRECIO DE VENTA","UTILIDAD PROD","VALOR DEL INVENTARIO"
    ]

    if not os.path.exists(ARCHIVO):
        df = pd.DataFrame(columns=columnas)
        df.to_excel(ARCHIVO, index=False)
        return df

    df = pd.read_excel(ARCHIVO)
    df.columns = df.columns.astype(str).str.strip().str.upper()

    for col in columnas:
        if col not in df.columns:
            df[col] = ""

    df = df[columnas]
    df = df.fillna("")
    return df


def guardar_excel(df):
    df.to_excel(ARCHIVO, index=False)


def aplicar_filtros(df):
    editoriales = request.args.getlist("editorial")
    categorias = request.args.getlist("categoria")

    editoriales = [e.upper() for e in editoriales if e.strip()]
    categorias = [c.upper() for c in categorias if c.strip()]

    if editoriales:
        df = df[df["EDITORIAL"].astype(str).str.upper().isin(editoriales)]

    if categorias:
        df = df[df["CATEGORIA"].astype(str).str.upper().isin(categorias)]

    return df


def opciones_filtros(df):
    editoriales = sorted(df["EDITORIAL"].dropna().astype(str).unique())
    categorias = sorted(df["CATEGORIA"].dropna().astype(str).unique())

    editoriales = [x for x in editoriales if x.strip() != ""]
    categorias = [x for x in categorias if x.strip() != ""]

    sugerencias = []

    for _, row in df.iterrows():
        codigo = str(row["CODIGO"]).strip()
        nombre = str(row["NOMBRE DEL PRODUCTO"]).strip()

        if codigo:
            sugerencias.append(codigo)
        if nombre:
            sugerencias.append(nombre)

    sugerencias = sorted(list(set(sugerencias)))
    return editoriales, categorias, sugerencias


@app.route("/inventario")
def inventario():
    if login_requerido():
        return redirect("/login")

    if session.get("user") != "PC1":
        return redirect("/")

    df_original = cargar_excel()
    df = aplicar_filtros(df_original)

    editoriales, categorias, sugerencias = opciones_filtros(df_original)

    # 🔥 NUEVO: lista completa de libros para buscador
    libros_inventario = []

    for _, row in df_original.iterrows():
        libros_inventario.append({
            "codigo": str(row["CODIGO"]).strip(),
            "nombre": str(row["NOMBRE DEL PRODUCTO"]).strip()
        })

    return render_template(
        "inventario.html",
        tabla=df.to_html(index=False, classes="tabla"),
        usuario=session.get("user"),
        editoriales=editoriales,
        categorias=categorias,
        sugerencias=sugerencias,
        libros_inventario=libros_inventario,
        editoriales_seleccionadas=request.args.getlist("editorial"),
        categorias_seleccionadas=request.args.getlist("categoria")
    )


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)