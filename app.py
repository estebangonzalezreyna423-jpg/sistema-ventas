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
def limpiar(valor):
    return str(valor).strip().upper() if valor else ""


def login_requerido():
    return "user" not in session


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
    buscar = request.args.get("buscar", "")

    editoriales = [e.upper() for e in editoriales if e.strip()]
    categorias = [c.upper() for c in categorias if c.strip()]

    if editoriales:
        df = df[df["EDITORIAL"].astype(str).str.upper().isin(editoriales)]

    if categorias:
        df = df[df["CATEGORIA"].astype(str).str.upper().isin(categorias)]

    if buscar:
        buscar = buscar.upper()
        df = df[
            df["CODIGO"].astype(str).str.upper().str.contains(buscar, na=False) |
            df["NOMBRE DEL PRODUCTO"].astype(str).str.upper().str.contains(buscar, na=False)
        ]

    return df


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

    df = aplicar_filtros(cargar_excel())

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
# INVENTARIO
# =============================
@app.route("/inventario")
def inventario():
    if login_requerido():
        return redirect("/login")

    if session.get("user") != "PC1":
        return redirect("/")

    df = aplicar_filtros(cargar_excel())

    return render_template(
        "inventario.html",
        tabla=df.to_html(index=False, classes="tabla"),
        usuario=session.get("user")
    )


# =============================
# CARRITO
# =============================
@app.route("/eliminar/<int:index>")
def eliminar(index):
    carrito = session.get("carrito", [])

    if 0 <= index < len(carrito):
        carrito.pop(index)

    session["carrito"] = carrito
    return redirect("/")


@app.route("/agregar", methods=["POST"])
def agregar():
    if login_requerido():
        return redirect("/login")

    df = cargar_excel()
    carrito = session.get("carrito", [])

    codigo = limpiar(request.form.get("codigo"))
    cantidad = int(request.form.get("cantidad") or 0)

    fila = df[df["CODIGO"].astype(str).str.upper() == codigo]

    if fila.empty:
        return redirect("/")

    item = fila.iloc[0]

    precio = float(item["COSTO UNITARIO"] or 0)

    carrito.append({
        "codigo": item["CODIGO"],
        "nombre": item["NOMBRE DEL PRODUCTO"],
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
    carrito = session.get("carrito", [])
    df = cargar_excel()

    conn = get_conn()
    cur = conn.cursor() if conn else None

    ahora = datetime.now()

    for item in carrito:
        codigo = limpiar(item["codigo"])

        idx = df[df["CODIGO"].astype(str).str.upper() == codigo].index

        if len(idx) > 0:
            i = idx[0]
            df.at[i, "STOCK"] = max(0, int(df.at[i, "STOCK"]) - item["cantidad"])

        if cur:
            cur.execute("""
                INSERT INTO ventas (usuario, codigo, nombre, cantidad, subtotal, metodo, fecha)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (
                session["user"],
                codigo,
                item["nombre"],
                item["cantidad"],
                item["subtotal"],
                metodo.upper(),
                ahora
            ))

    if conn:
        conn.commit()
        cur.close()
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
        return render_template("ventas.html", ventas=[])

    df = pd.read_sql("SELECT * FROM ventas ORDER BY fecha DESC", conn)
    conn.close()

    df.columns = df.columns.str.lower()

    return render_template(
        "ventas.html",
        ventas=df.to_dict(orient="records"),
        usuario=session.get("user")
    )


# =============================
# 🔥 ELIMINAR VENTA (ARREGLADO)
# =============================
@app.route("/ventas/eliminar/<int:id>")
def eliminar_venta(id):
    if login_requerido():
        return redirect("/login")

    if session.get("user") != "PC1":
        return redirect("/ventas")

    conn = get_conn()

    if conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM ventas WHERE id = %s", (id,))
        conn.commit()
        cur.close()
        conn.close()

    return redirect("/ventas")


# =============================
# INIT
# =============================
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)