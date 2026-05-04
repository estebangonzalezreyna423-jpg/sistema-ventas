from flask import Flask, render_template, request, redirect, session, send_file
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import psycopg2
from io import BytesIO

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "clave_super_segura_123")

DATABASE_URL = os.environ.get("DATABASE_URL")

USUARIOS = {
    "admin": {"password": "Gladis26", "rol": "admin"},
    "oficina1": {"password": "Cepas1", "rol": "oficina"},
    "oficina2": {"password": "Cepas2", "rol": "oficina"},
    "biblioteca": {"password": "Biblioteca26", "rol": "biblioteca"}
}

# ================= DB =================
def get_conn():
    if not DATABASE_URL:
        return None
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print("ERROR DB:", e)
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventario (
            id SERIAL PRIMARY KEY,
            codigo TEXT UNIQUE,
            nombre TEXT,
            editorial TEXT,
            categoria TEXT,
            compras INT DEFAULT 0,
            ventas INT DEFAULT 0,
            stock INT DEFAULT 0,
            costo_unitario FLOAT DEFAULT 0,
            precio_venta FLOAT DEFAULT 0,
            utilidad_prod FLOAT DEFAULT 0,
            valor_inventario FLOAT DEFAULT 0
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


# ================= UTILS =================
def limpiar(valor):
    return str(valor).strip().upper() if valor else ""


def login_requerido():
    return "user" not in session


def es_admin():
    return session.get("rol") == "admin"


def hora_peru():
    return datetime.now(ZoneInfo("America/Lima")).replace(tzinfo=None)


def numero(valor, tipo=float):
    try:
        if valor in [None, ""]:
            return 0
        return tipo(valor)
    except:
        return 0


# ================= INVENTARIO =================
def cargar_excel():
    conn = get_conn()
    if not conn:
        return pd.DataFrame()

    df = pd.read_sql("SELECT * FROM inventario ORDER BY codigo ASC", conn)
    conn.close()
    return df.fillna("")


def buscar_producto(busqueda):
    conn = get_conn()
    if not conn:
        return None

    cur = conn.cursor()
    busqueda = limpiar(busqueda)

    cur.execute("""
        SELECT codigo, nombre, stock, costo_unitario
        FROM inventario
        WHERE UPPER(codigo)=%s OR UPPER(nombre)=%s
        LIMIT 1
    """, (busqueda, busqueda))

    p = cur.fetchone()
    cur.close()
    conn.close()

    if not p:
        return None

    return {
        "codigo": p[0],
        "nombre": p[1],
        "stock": p[2],
        "costo_unitario": p[3]
    }


# ================= LOGIN =================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("usuario", "").lower()
        password = request.form.get("password")

        if user in USUARIOS and USUARIOS[user]["password"] == password:
            session["user"] = user
            session["rol"] = USUARIOS[user]["rol"]
            session["carrito"] = []
            return redirect("/")

        return render_template("login.html", error="Error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ================= INDEX (CORREGIDO) =================
@app.route("/")
def index():
    if login_requerido():
        return redirect("/login")

    carrito = session.get("carrito", [])
    total = sum(i["subtotal"] for i in carrito)

    df = cargar_excel()

    editoriales = []
    categorias = []
    sugerencias = []
    tabla = ""

    if not df.empty:
        if "editorial" in df.columns:
            editoriales = sorted(df["editorial"].dropna().astype(str).unique())

        if "categoria" in df.columns:
            categorias = sorted(df["categoria"].dropna().astype(str).unique())

        for _, row in df.iterrows():
            sugerencias.append(str(row["codigo"]))
            sugerencias.append(str(row["nombre"]))

        sugerencias = sorted(list(set(sugerencias)))
        tabla = df.to_html(index=False, classes="tabla")

    return render_template(
        "index.html",
        carrito=carrito,
        total=round(total, 2),
        usuario=session["user"],
        rol=session["rol"],
        editoriales=editoriales,
        categorias=categorias,
        sugerencias=sugerencias,
        tabla=tabla
    )


# ================= ELIMINAR DEL CARRITO =================
@app.route("/eliminar/<int:index>")
def eliminar(index):
    if login_requerido():
        return redirect("/login")

    carrito = session.get("carrito", [])

    if 0 <= index < len(carrito):
        carrito.pop(index)

    session["carrito"] = carrito
    return redirect("/")


# ================= AGREGAR =================
@app.route("/agregar", methods=["POST"])
def agregar():
    if login_requerido():
        return redirect("/login")

    carrito = session.get("carrito", [])

    codigo = request.form.get("codigo")
    cantidad = int(request.form.get("cantidad"))

    producto = buscar_producto(codigo)
    if not producto:
        return redirect("/")

    if cantidad > producto["stock"]:
        return redirect("/")

    carrito.append({
        "codigo": producto["codigo"],
        "nombre": producto["nombre"],
        "precio": producto["costo_unitario"],
        "cantidad": cantidad,
        "subtotal": producto["costo_unitario"] * cantidad
    })

    session["carrito"] = carrito
    return redirect("/")


# ================= FINALIZAR (CON FECHA) =================
@app.route("/finalizar/<metodo>", methods=["POST"])
def finalizar(metodo):
    if login_requerido():
        return redirect("/login")

    carrito = session.get("carrito", [])
    if not carrito:
        return redirect("/")

    conn = get_conn()
    if not conn:
        return redirect("/")

    cur = conn.cursor()

    fecha_manual = request.form.get("fecha_venta")

    if fecha_manual:
        try:
            ahora = datetime.strptime(fecha_manual, "%Y-%m-%dT%H:%M")
        except:
            ahora = hora_peru()
    else:
        ahora = hora_peru()

    try:
        for item in carrito:
            codigo = limpiar(item["codigo"])
            cantidad = item["cantidad"]

            cur.execute("SELECT stock, ventas FROM inventario WHERE UPPER(codigo)=%s", (codigo,))
            prod = cur.fetchone()

            stock = prod[0]
            ventas = prod[1]

            nuevo_stock = stock - cantidad
            nuevas_ventas = ventas + cantidad

            cur.execute("""
                UPDATE inventario
                SET stock=%s, ventas=%s
                WHERE UPPER(codigo)=%s
            """, (nuevo_stock, nuevas_ventas, codigo))

            cur.execute("""
                INSERT INTO ventas (usuario, codigo, nombre, cantidad, subtotal, metodo, fecha)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (
                session["user"],
                codigo,
                item["nombre"],
                cantidad,
                item["subtotal"],
                metodo.upper(),
                ahora
            ))

        conn.commit()

    except Exception as e:
        print("ERROR:", e)
        conn.rollback()

    finally:
        cur.close()
        conn.close()

    session["carrito"] = []
    return redirect("/")


# ================= VENTAS =================
@app.route("/ventas")
def ventas():
    if login_requerido():
        return redirect("/login")

    conn = get_conn()
    df = pd.read_sql("SELECT * FROM ventas ORDER BY fecha DESC", conn)
    conn.close()

    return render_template(
        "ventas.html",
        ventas=df.to_dict(orient="records"),
        usuario=session["user"]
    )


# ================= INIT =================
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)