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
# INDEX
# =============================
@app.route("/")
def index():
    if login_requerido():
        return redirect("/login")

    df = cargar_excel()
    carrito = session.get("carrito", [])
    total = sum(i["subtotal"] for i in carrito)

    return render_template(
        "index.html",
        tabla=df.to_html(index=False, classes="tabla"),
        carrito=carrito,
        total=total,
        usuario=session.get("user")
    )


# =============================
# INVENTARIO (SOLO PC1)
# =============================
@app.route("/inventario")
def inventario():
    if login_requerido():
        return redirect("/login")

    if session.get("user") != "PC1":
        return redirect("/")

    df = cargar_excel()

    return render_template(
        "inventario.html",
        tabla=df.to_html(index=False, classes="tabla"),
        usuario=session.get("user")
    )


# =============================
# AGREGAR LIBRO
# =============================
@app.route("/inventario/agregar", methods=["POST"])
def agregar_libro():
    if login_requerido() or session.get("user") != "PC1":
        return redirect("/inventario")

    df = cargar_excel()

    try:
        codigo = limpiar(request.form.get("codigo"))

        # evitar duplicados
        if codigo in df["CODIGO"].astype(str).str.upper().values:
            return redirect("/inventario")

        nuevo = {
            "CODIGO": codigo,
            "NOMBRE": request.form.get("nombre"),
            "PRECIO": float(request.form.get("precio")),
            "CATEGORIA": request.form.get("categoria"),
            "EDITORIAL": request.form.get("editorial"),
            "STOCK": int(request.form.get("stock"))
        }
    except:
        return redirect("/inventario")

    df = pd.concat([df, pd.DataFrame([nuevo])], ignore_index=True)
    guardar_excel(df)

    return redirect("/inventario")


# =============================
# EDITAR STOCK / PRECIO
# =============================
@app.route("/inventario/editar", methods=["POST"])
def editar_inventario():
    if login_requerido() or session.get("user") != "PC1":
        return redirect("/inventario")

    df = cargar_excel()
    codigo = limpiar(request.form.get("codigo"))

    idx = df[df["CODIGO"].astype(str).str.upper() == codigo].index

    if len(idx) > 0:
        i = idx[0]

        if request.form.get("stock"):
            df.at[i, "STOCK"] = int(request.form.get("stock"))

        if request.form.get("precio"):
            df.at[i, "PRECIO"] = float(request.form.get("precio"))

        guardar_excel(df)

    return redirect("/inventario")


# =============================
# ELIMINAR LIBRO
# =============================
@app.route("/inventario/eliminar", methods=["POST"])
def eliminar_libro():
    if login_requerido() or session.get("user") != "PC1":
        return redirect("/inventario")

    df = cargar_excel()
    codigo = limpiar(request.form.get("codigo"))

    df = df[df["CODIGO"].astype(str).str.upper() != codigo]
    guardar_excel(df)

    return redirect("/inventario")


# =============================
# CARRITO
# =============================
@app.route("/agregar", methods=["POST"])
def agregar():
    if login_requerido():
        return redirect("/login")

    df = cargar_excel()
    carrito = session.get("carrito", [])

    codigo = limpiar(request.form.get("codigo"))
    cantidad = int(request.form.get("cantidad"))

    fila = df[df["CODIGO"].astype(str).str.upper() == codigo]

    if fila.empty:
        return redirect("/")

    item = fila.iloc[0]

    try:
        stock_actual = int(item["STOCK"])
    except:
        return redirect("/")

    if stock_actual < cantidad:
        return redirect("/")

    carrito.append({
        "codigo": item["CODIGO"],
        "nombre": item["NOMBRE"],
        "precio": float(item["PRECIO"]),
        "cantidad": cantidad,
        "subtotal": float(item["PRECIO"]) * cantidad
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

    for i in carrito:
        idx = df[df["CODIGO"] == i["codigo"]].index

        if len(idx) > 0:
            pos = idx[0]
            nuevo_stock = int(df.at[pos, "STOCK"]) - i["cantidad"]
            df.at[pos, "STOCK"] = max(0, nuevo_stock)

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
        return "❌ No hay base de datos conectada"

    df = pd.read_sql("SELECT * FROM ventas ORDER BY fecha DESC", conn)
    conn.close()

    return render_template(
        "ventas.html",
        tabla=df.to_html(index=False, classes="tabla"),
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
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)