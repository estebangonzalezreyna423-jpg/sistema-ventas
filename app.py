from flask import Flask, render_template, request, redirect, session
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
COLUMNAS_BASE = ["CODIGO", "NOMBRE", "PRECIO", "CATEGORIA", "EDITORIAL", "STOCK"]

def cargar_excel():
    if not os.path.exists(ARCHIVO):
        df = pd.DataFrame(columns=COLUMNAS_BASE)
        df.to_excel(ARCHIVO, index=False)
        return df

    df = pd.read_excel(ARCHIVO)
    df.columns = df.columns.astype(str).str.strip().str.upper()

    for col in COLUMNAS_BASE:
        if col not in df.columns:
            df[col] = None

    # LIMPIEZA SEGURA
    df["PRECIO"] = pd.to_numeric(df["PRECIO"], errors="coerce").fillna(0)
    df["STOCK"] = pd.to_numeric(df["STOCK"], errors="coerce").fillna(0).astype(int)

    return df


def guardar_excel(df):
    df.to_excel(ARCHIVO, index=False)


def limpiar(valor):
    return str(valor).strip().upper() if valor else ""


def login_requerido():
    return "user" not in session


# =============================
# LOGIN
# =============================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = limpiar(request.form.get("usuario"))
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
# INDEX (ARREGLADO COMPLETO)
# =============================
@app.route("/")
def index():
    if login_requerido():
        return redirect("/login")

    df = cargar_excel()

    editorial = request.args.get("editorial")
    categoria = request.args.get("categoria")

    if editorial:
        df = df[df["EDITORIAL"].astype(str).str.strip() == editorial]

    if categoria:
        df = df[df["CATEGORIA"].astype(str).str.strip() == categoria]

    df_base = cargar_excel()
    editoriales = df_base["EDITORIAL"].dropna().astype(str).unique().tolist()
    categorias = df_base["CATEGORIA"].dropna().astype(str).unique().tolist()

    # 🔥 TABLA BONITA (SOLO VISUAL)
    df_mostrar = df.copy()

    df_mostrar = df_mostrar.rename(columns={
        "CODIGO": "CODIGO",
        "NOMBRE": "NOMBRE DEL PRODUCTO",
        "EDITORIAL": "EDITORIAL",
        "CATEGORIA": "CATEGORIA",
        "STOCK": "STOCK",
        "PRECIO": "PRECIO DE VENTA"
    })

    tabla = df_mostrar.to_html(index=False, classes="tabla")

    carrito = session.get("carrito", [])
    total = sum(i["subtotal"] for i in carrito)

    return render_template(
        "index.html",
        tabla=tabla,
        carrito=carrito,
        total=total,
        usuario=session.get("user"),
        editoriales=editoriales,
        categorias=categorias,
        editorial_actual=editorial,
        categoria_actual=categoria
    )


# =============================
# INVENTARIO
# =============================
@app.route("/inventario")
def inventario():
    if login_requerido():
        return redirect("/login")

    if session.get("user") != "PC1":
        return redirect("/")

    df = cargar_excel()

    df = df.rename(columns={
        "CODIGO": "CODIGO",
        "NOMBRE": "NOMBRE DEL PRODUCTO",
        "EDITORIAL": "EDITORIAL",
        "CATEGORIA": "CATEGORIA",
        "STOCK": "STOCK",
        "PRECIO": "PRECIO DE VENTA"
    })

    return render_template(
        "inventario.html",
        tabla=df.to_html(index=False, classes="tabla"),
        usuario=session.get("user")
    )


# =============================
# AGREGAR AL CARRITO (100% FIX)
# =============================
@app.route("/agregar", methods=["POST"])
def agregar():
    if login_requerido():
        return redirect("/login")

    df = cargar_excel()
    carrito = session.get("carrito", [])

    codigo = limpiar(request.form.get("codigo"))
    cantidad = request.form.get("cantidad")

    try:
        cantidad = int(cantidad)
        if cantidad <= 0:
            return redirect("/")
    except:
        return redirect("/")

    fila = df[df["CODIGO"].astype(str).str.upper() == codigo]

    if fila.empty:
        return redirect("/")

    item = fila.iloc[0]

    stock = int(item["STOCK"])
    if stock < cantidad:
        return redirect("/")

    precio = float(item["PRECIO"])

    carrito.append({
        "codigo": item["CODIGO"],
        "nombre": item["NOMBRE"],
        "precio": precio,
        "cantidad": cantidad,
        "subtotal": precio * cantidad
    })

    session["carrito"] = carrito
    return redirect("/")


# =============================
# ELIMINAR ITEM DEL CARRITO
# =============================
@app.route("/eliminar/<int:index>")
def eliminar(index):
    carrito = session.get("carrito", [])

    if 0 <= index < len(carrito):
        carrito.pop(index)

    session["carrito"] = carrito
    return redirect("/")


# =============================
# FINALIZAR VENTA
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
    now = datetime.now()

    for i in carrito:
        idx = df[df["CODIGO"] == i["codigo"]].index

        if len(idx) > 0:
            pos = idx[0]
            df.at[pos, "STOCK"] = max(0, int(df.at[pos, "STOCK"]) - i["cantidad"])

        if conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO ventas (usuario, codigo, nombre, cantidad, subtotal, metodo, fecha)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (
                session["user"],
                i["codigo"],
                i["nombre"],
                i["cantidad"],
                i["subtotal"],
                metodo.upper(),
                now
            ))
            conn.commit()
            cur.close()

    if conn:
        conn.close()

    guardar_excel(df)
    session["carrito"] = []

    return redirect("/")


# =============================
# VENTAS
# =============================
@app.route("/ventas")
def ventas():
    conn = get_conn()

    if not conn:
        return render_template("ventas.html", ventas=[], total=0, total_efectivo=0, total_yape=0)

    df = pd.read_sql("SELECT * FROM ventas ORDER BY fecha DESC", conn)
    conn.close()

    df.columns = df.columns.str.lower()
    ventas = df.to_dict(orient="records")

    return render_template(
        "ventas.html",
        ventas=ventas,
        total=df["subtotal"].sum() if not df.empty else 0,
        total_efectivo=df[df["metodo"] == "EFECTIVO"]["subtotal"].sum() if not df.empty else 0,
        total_yape=df[df["metodo"] == "YAPE"]["subtotal"].sum() if not df.empty else 0,
        usuario=session.get("user")
    )


# =============================
# INIT
# =============================
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)