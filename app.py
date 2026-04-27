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
    return psycopg2.connect(DATABASE_URL)


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
# UTILIDADES SEGURAS
# =============================
def cargar_excel():
    if not os.path.exists(ARCHIVO):
        return pd.DataFrame()

    try:
        for i in range(10):
            df = pd.read_excel(ARCHIVO, header=i)
            df.columns = df.columns.str.strip().str.upper()

            if "CODIGO" in df.columns:
                return df

        return pd.DataFrame()

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
    if valor is None:
        return ""
    return str(valor).strip().upper()


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
        else:
            return render_template("login.html", error="Credenciales incorrectas")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# =============================
# INDEX (ARREGLADO)
# =============================
@app.route("/")
def index():
    if login_requerido():
        return redirect("/login")

    df = cargar_excel()

    carrito = session.get("carrito", [])
    total = sum(item.get("subtotal", 0) for item in carrito)

    col_editorial = buscar_columna(df, ["EDITORIAL"])
    col_categoria = buscar_columna(df, ["CATEGORIA"])

    editoriales = []
    categorias = []

    if col_editorial:
        editoriales = sorted(df[col_editorial].dropna().astype(str).str.upper().unique())

    if col_categoria:
        categorias = sorted(df[col_categoria].dropna().astype(str).str.upper().unique())

    editorial_filtro = limpiar_texto(request.args.get("editorial"))
    categoria_filtro = limpiar_texto(request.args.get("categoria"))

    df_filtrado = df.copy()

    if col_editorial and editorial_filtro:
        df_filtrado = df_filtrado[df_filtrado[col_editorial].astype(str).str.upper() == editorial_filtro]

    if col_categoria and categoria_filtro:
        df_filtrado = df_filtrado[df_filtrado[col_categoria].astype(str).str.upper() == categoria_filtro]

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
# AGREGAR (ARREGLADO - EVITA CRASH)
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

    # 🔥 SI NO HAY COLUMNAS, NO ROMPE
    if not all([col_codigo, col_nombre, col_precio, col_stock]):
        return redirect("/")

    fila = df[
        (df[col_codigo].astype(str).str.upper() == codigo) |
        (df[col_nombre].astype(str).str.upper().str.contains(codigo, na=False))
    ]

    if fila.empty:
        return redirect("/")

    producto = fila.iloc[0]

    try:
        precio = float(str(producto[col_precio]).replace("S/", "").strip())
        stock = float(producto[col_stock])
    except:
        return redirect("/")

    if stock < cantidad:
        return redirect("/")

    carrito.append({
        "codigo": producto[col_codigo],
        "nombre": producto[col_nombre],
        "precio": precio,
        "cantidad": cantidad,
        "subtotal": precio * cantidad
    })

    session["carrito"] = carrito
    return redirect("/")


# =============================
# ELIMINAR
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
    df = cargar_excel()

    conn = get_conn()
    cur = conn.cursor() if conn else None

    ahora = datetime.now()

    col_codigo = buscar_columna(df, ["CODIGO"])
    col_stock = buscar_columna(df, ["STOCK"])
    col_nombre = buscar_columna(df, ["NOMBRE"])

    for item in carrito:
        if col_codigo and col_stock:
            fila = df[df[col_codigo] == item["codigo"]].index

            if len(fila) > 0:
                i = fila[0]
                df.at[i, col_stock] -= item["cantidad"]

                if cur:
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

    if conn:
        conn.commit()
        cur.close()
        conn.close()

    df.to_excel(ARCHIVO, index=False)
    session["carrito"] = []

    return redirect("/")


# =============================
# VENTAS (SEGURO)
# =============================
@app.route("/ventas")
def ver_ventas():
    if login_requerido():
        return redirect("/login")

    try:
        conn = get_conn()

        if not conn:
            return "❌ Sin base de datos"

        df = pd.read_sql("SELECT * FROM ventas ORDER BY fecha DESC", conn)
        conn.close()

        total = df["subtotal"].sum() if not df.empty else 0

        return render_template(
            "ventas.html",
            tabla=df.to_html(index=False, classes="tabla"),
            total=total,
            usuario=session.get("user")
        )

    except:
        return "❌ Error cargando ventas"


# =============================
# DESCARGAR EXCEL
# =============================
@app.route("/descargar_ventas")
def descargar_ventas():
    conn = get_conn()
    if not conn:
        return "❌ Sin conexión"

    df = pd.read_sql("SELECT * FROM ventas ORDER BY fecha DESC", conn)
    conn.close()

    archivo = "reporte_ventas.xlsx"
    df.to_excel(archivo, index=False)

    return send_file(archivo, as_attachment=True)


# =============================
# INIT
# =============================
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))