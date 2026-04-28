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
# UTILIDADES (🔥 CLAVE)
# =============================
def cargar_excel():
    if not os.path.exists(ARCHIVO):
        return pd.DataFrame()

    try:
        for i in range(5):
            df = pd.read_excel(ARCHIVO, header=i)
            df.columns = df.columns.astype(str).str.strip().str.upper()

            if "CODIGO" in df.columns:
                return df

        return pd.DataFrame()
    except:
        return pd.DataFrame()


def buscar_columna(df, palabras):
    for col in df.columns:
        for p in palabras:
            if p in col:
                return col
    return None


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
# INDEX (🔥 ESTABLE)
# =============================
@app.route("/")
def index():
    if login_requerido():
        return redirect("/login")

    df = cargar_excel()
    if df.empty:
        return "❌ No hay inventario válido"

    col_editorial = buscar_columna(df, ["EDITORIAL"])
    col_categoria = buscar_columna(df, ["CATEGORIA"])

    editoriales = sorted(df[col_editorial].dropna().astype(str).unique()) if col_editorial else []
    categorias = sorted(df[col_categoria].dropna().astype(str).unique()) if col_categoria else []

    editorial = limpiar(request.args.get("editorial"))
    categoria = limpiar(request.args.get("categoria"))

    if editorial and col_editorial:
        df = df[df[col_editorial].astype(str).str.upper() == editorial]

    if categoria and col_categoria:
        df = df[df[col_categoria].astype(str).str.upper() == categoria]

    carrito = session.get("carrito", [])
    total = sum(i["subtotal"] for i in carrito)

    return render_template(
        "index.html",
        tabla=df.to_html(index=False, classes="tabla"),
        carrito=carrito,
        total=total,
        usuario=session.get("user"),
        editoriales=editoriales,
        categorias=categorias,
        editorial_actual=editorial,
        categoria_actual=categoria
    )


# =============================
# INVENTARIO (🔥 FIX)
# =============================
@app.route("/inventario")
def inventario():
    if login_requerido():
        return redirect("/login")

    if session.get("user") != "PC1":
        return redirect("/")

    df = cargar_excel()

    if df.empty:
        return "❌ Inventario vacío o mal formado"

    return render_template(
        "inventario.html",
        tabla=df.to_html(index=False, classes="tabla"),
        usuario=session.get("user")
    )


# =============================
# AGREGAR (🔥 CLAVE ARREGLADO)
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

    col_codigo = buscar_columna(df, ["CODIGO"])
    col_nombre = buscar_columna(df, ["NOMBRE"])
    col_precio = buscar_columna(df, ["PRECIO", "COSTO"])
    col_stock = buscar_columna(df, ["STOCK"])

    if not all([col_codigo, col_nombre, col_precio, col_stock]):
        return "❌ Columnas mal en Excel"

    fila = df[
        (df[col_codigo].astype(str).str.upper() == codigo) |
        (df[col_nombre].astype(str).str.upper().str.contains(codigo, na=False))
    ]

    if fila.empty:
        return redirect("/")

    item = fila.iloc[0]

    try:
        precio = float(str(item[col_precio]).replace("S/", "").strip())
        stock = int(item[col_stock])
    except:
        return redirect("/")

    if stock < cantidad:
        return redirect("/")

    carrito.append({
        "codigo": item[col_codigo],
        "nombre": item[col_nombre],
        "precio": precio,
        "cantidad": cantidad,
        "subtotal": precio * cantidad
    })

    session["carrito"] = carrito
    return redirect("/")


# =============================
# ELIMINAR CARRITO
# =============================
@app.route("/eliminar/<int:index>")
def eliminar(index):
    carrito = session.get("carrito", [])

    if 0 <= index < len(carrito):
        carrito.pop(index)

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
    now = datetime.now()

    col_codigo = buscar_columna(df, ["CODIGO"])
    col_stock = buscar_columna(df, ["STOCK"])
    col_nombre = buscar_columna(df, ["NOMBRE"])
    col_ventas = buscar_columna(df, ["VENTA"])  # 🔥 ESTA ES LA CLAVE

    for i in carrito:
        idx = df[df[col_codigo] == i["codigo"]].index

        if len(idx) > 0:
            pos = idx[0]

            # 🔻 BAJA STOCK
            df.at[pos, col_stock] = max(0, int(df.at[pos, col_stock]) - i["cantidad"])

            # 🔥 SUBE VENTAS (ESTO FALTABA)
            if col_ventas:
                actual = df.at[pos, col_ventas]
                try:
                    actual = int(actual)
                except:
                    actual = 0

                df.at[pos, col_ventas] = actual + i["cantidad"]

        # GUARDAR EN BD
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

    df.to_excel(ARCHIVO, index=False)
    session["carrito"] = []

    return redirect("/")


# =============================
# VENTAS (🔥 FIX TOTAL)
# =============================
@app.route("/ventas")
def ventas():
    conn = get_conn()

    if not conn:
        return render_template("ventas.html", ventas=[], total=0, total_efectivo=0, total_yape=0)

    try:
        df = pd.read_sql("SELECT * FROM ventas ORDER BY fecha DESC", conn)
        conn.close()
    except:
        return "❌ Error leyendo ventas"

    if df.empty:
        return render_template("ventas.html", ventas=[], total=0, total_efectivo=0, total_yape=0)

    df.columns = df.columns.str.lower()

    return render_template(
        "ventas.html",
        ventas=df.to_dict(orient="records"),
        total=df["subtotal"].sum(),
        total_efectivo=df[df["metodo"] == "EFECTIVO"]["subtotal"].sum(),
        total_yape=df[df["metodo"] == "YAPE"]["subtotal"].sum(),
        usuario=session.get("user")
    )


# =============================
# INIT
# =============================
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)