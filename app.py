from flask import Flask, render_template, request, redirect, session, send_file
import pandas as pd
from datetime import datetime
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

# =============================
# DB
# =============================
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


# =============================
# UTILIDADES
# =============================
def cargar_excel():
    if not os.path.exists(ARCHIVO):
        return pd.DataFrame()

    try:
        df = pd.read_excel(ARCHIVO)
        df.columns = df.columns.astype(str).str.strip().str.upper()
        return df
    except:
        return pd.DataFrame()


def buscar_columna(df, palabras):
    if df is None or df.empty:
        return None
    for col in df.columns:
        for p in palabras:
            if p in col:
                return col
    return None


def limpiar_texto(valor):
    return str(valor).strip().upper() if valor else ""


def login_requerido():
    return "user" not in session


# =============================
# LOGIN
# =============================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = limpiar_texto(request.form.get("usuario"))
        password = request.form.get("password")

        if user in USUARIOS and USUARIOS[user] == password:
            session["user"] = user
            session["carrito"] = []
            return redirect("/")
        return render_template("login.html", error="Credenciales incorrectas")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# =============================
# INDEX
# =============================
@app.route("/")
def index():
    if login_requerido():
        return redirect("/login")

    df = cargar_excel()

    carrito = session.get("carrito", [])
    total = sum(i.get("subtotal", 0) for i in carrito)

    col_editorial = buscar_columna(df, ["EDITORIAL"])
    col_categoria = buscar_columna(df, ["CATEGORIA"])

    editorial_filtro = limpiar_texto(request.args.get("editorial"))
    categoria_filtro = limpiar_texto(request.args.get("categoria"))

    df_filtrado = df.copy()

    if col_editorial and editorial_filtro:
        df_filtrado = df_filtrado[df_filtrado[col_editorial].astype(str).str.upper() == editorial_filtro]

    if col_categoria and categoria_filtro:
        df_filtrado = df_filtrado[df_filtrado[col_categoria].astype(str).str.upper() == categoria_filtro]

    editoriales = sorted(df[col_editorial].dropna().astype(str).str.upper().unique()) if col_editorial else []
    categorias = sorted(df[col_categoria].dropna().astype(str).str.upper().unique()) if col_categoria else []

    return render_template(
        "index.html",
        tabla=df_filtrado.to_html(index=False, classes="tabla"),
        carrito=carrito,
        total=total,
        editoriales=editoriales,
        categorias=categorias,
        editorial_actual=editorial_filtro,
        categoria_actual=categoria_filtro,
        usuario=session.get("user")
    )


# =============================
# INVENTARIO
# =============================
@app.route("/inventario")
def inventario():
    if login_requerido():
        return redirect("/login")

    df = cargar_excel()

    return render_template(
        "inventario.html",
        tabla=df.to_html(index=False, classes="tabla"),
        usuario=session.get("user")
    )


@app.route("/inventario/actualizar", methods=["POST"])
def actualizar_inventario():
    if login_requerido():
        return redirect("/login")

    if session.get("user") != "PC1":
        return redirect("/inventario")

    df = cargar_excel()

    codigo = limpiar_texto(request.form.get("codigo"))
    stock = request.form.get("stock")
    precio = request.form.get("precio")

    col_codigo = buscar_columna(df, ["CODIGO"])
    col_stock = buscar_columna(df, ["STOCK"])
    col_precio = buscar_columna(df, ["COSTO"])

    if not col_codigo:
        return redirect("/inventario")

    idx = df[df[col_codigo].astype(str).str.upper() == codigo].index

    if len(idx) > 0:
        i = idx[0]

        if stock:
            df.at[i, col_stock] = float(stock)

        if col_precio and precio:
            df.at[i, col_precio] = float(precio)

        df.to_excel(ARCHIVO, index=False)

    return redirect("/inventario")


# =============================
# AGREGAR
# =============================
@app.route("/agregar", methods=["POST"])
def agregar():
    if login_requerido():
        return redirect("/login")

    df = cargar_excel()
    carrito = session.get("carrito", [])

    codigo = limpiar_texto(request.form.get("codigo"))
    cantidad = int(request.form.get("cantidad"))

    col_codigo = buscar_columna(df, ["CODIGO"])
    col_nombre = buscar_columna(df, ["NOMBRE"])
    col_precio = buscar_columna(df, ["COSTO"])
    col_stock = buscar_columna(df, ["STOCK"])

    fila = df[
        (df[col_codigo].astype(str).str.upper() == codigo) |
        (df[col_nombre].astype(str).str.upper().str.contains(codigo, na=False))
    ]

    if fila.empty:
        return redirect("/")

    p = fila.iloc[0]

    try:
        precio = float(str(p[col_precio]).replace("S/", "").strip())
        stock = float(p[col_stock])
    except:
        return redirect("/")

    if stock < cantidad:
        return redirect("/")

    carrito.append({
        "codigo": p[col_codigo],
        "nombre": p[col_nombre],
        "precio": precio,
        "cantidad": cantidad,
        "subtotal": precio * cantidad
    })

    session["carrito"] = carrito
    return redirect("/")


# =============================
# FINALIZAR
# =============================
@app.route("/finalizar/<metodo>")
def finalizar(metodo):
    if login_requerido():
        return redirect("/login")

    carrito = session.get("carrito", [])
    if not carrito:
        return redirect("/")

    df = cargar_excel()
    conn = get_conn()
    ahora = datetime.now()

    col_codigo = buscar_columna(df, ["CODIGO"])
    col_stock = buscar_columna(df, ["STOCK"])
    col_nombre = buscar_columna(df, ["NOMBRE"])

    for item in carrito:
        try:
            idx = df[df[col_codigo] == item["codigo"]].index
            if len(idx) == 0:
                continue

            i = idx[0]
            df.at[i, col_stock] -= item["cantidad"]

            if conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO ventas (usuario, codigo, nombre, cantidad, subtotal, metodo, fecha)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                """, (
                    session["user"],
                    item["codigo"],
                    item["nombre"],
                    item["cantidad"],
                    item["subtotal"],
                    metodo.upper(),
                    ahora
                ))
                conn.commit()
                cur.close()

        except:
            pass

    if conn:
        conn.close()

    df.to_excel(ARCHIVO, index=False)
    session["carrito"] = []

    return redirect("/")


# =============================
# VENTAS (CON TOTALES SEPARADOS)
# =============================
@app.route("/ventas")
def ver_ventas():
    if login_requerido():
        return redirect("/login")

    conn = get_conn()
    if not conn:
        return "❌ Sin base de datos"

    df = pd.read_sql("SELECT * FROM ventas ORDER BY fecha DESC", conn)
    conn.close()

    total = float(df["subtotal"].sum()) if not df.empty else 0

    total_efectivo = 0
    total_yape = 0

    if not df.empty and "metodo" in df.columns:
        total_efectivo = float(df[df["metodo"] == "EFECTIVO"]["subtotal"].sum())
        total_yape = float(df[df["metodo"] == "YAPE"]["subtotal"].sum())

    return render_template(
        "ventas.html",
        tabla=df.to_html(index=False, classes="tabla"),
        total=total,
        total_efectivo=total_efectivo,
        total_yape=total_yape,
        usuario=session.get("user")
    )


# =============================
# DESCARGAR
# =============================
@app.route("/descargar_ventas")
def descargar_ventas():
    conn = get_conn()
    if not conn:
        return "❌ Sin conexión"

    df = pd.read_sql("SELECT * FROM ventas ORDER BY fecha DESC", conn)
    conn.close()

    file = "ventas.xlsx"
    df.to_excel(file, index=False)

    return send_file(file, as_attachment=True)


# =============================
# INIT
# =============================
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))