from flask import Flask, render_template, request, redirect, session
import pandas as pd
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "clave_super_segura_123")

# 📁 ARCHIVOS
ARCHIVO = "inventario.xlsx"
ARCHIVO_VENTAS = "ventas.xlsx"

# 👤 USUARIOS
USUARIOS = {
    "PC1": "123",
    "PC2": "123",
    "PC3": "123"
}

# =============================
# 🔧 FUNCIONES
# =============================

def archivo_existe(path):
    return os.path.exists(path)

def cargar_excel():
    if not archivo_existe(ARCHIVO):
        print("❌ No existe inventario.xlsx")
        return pd.DataFrame()

    try:
        for i in range(10):
            df = pd.read_excel(ARCHIVO, header=i)
            df.columns = df.columns.str.strip().str.upper()

            if "CODIGO" in df.columns:
                return df

        print("❌ No se encontró columna CODIGO")
        return pd.DataFrame()

    except Exception as e:
        print("❌ Error leyendo Excel:", e)
        return pd.DataFrame()


def buscar_columna(df, palabras):
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
# 🔐 LOGIN
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
            return render_template("login.html", error="Usuario o contraseña incorrectos")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# =============================
# 🏠 INDEX
# =============================

@app.route("/")
def index():
    if login_requerido():
        return redirect("/login")

    df = cargar_excel()
    carrito = session.get("carrito", [])

    total = sum(item["subtotal"] for item in carrito)

    if df.empty:
        return "❌ Error: inventario.xlsx no encontrado o vacío"

    col_editorial = buscar_columna(df, ["EDITORIAL"])
    col_categoria = buscar_columna(df, ["CATEGORIA"])

    editoriales = sorted(df[col_editorial].dropna().astype(str).str.upper().unique()) if col_editorial else []
    categorias = sorted(df[col_categoria].dropna().astype(str).str.upper().unique()) if col_categoria else []

    return render_template(
        "index.html",
        tabla=df.to_html(index=False, classes="tabla"),
        carrito=carrito,
        total=total,
        editoriales=editoriales,
        categorias=categorias,
        usuario=session.get("user")
    )


# =============================
# ➕ AGREGAR
# =============================

@app.route("/agregar", methods=["POST"])
def agregar():
    if login_requerido():
        return redirect("/login")

    carrito = session.get("carrito", [])
    df = cargar_excel()

    if df.empty:
        return "Error cargando inventario"

    try:
        busqueda = limpiar_texto(request.form.get("codigo"))
        cantidad = int(request.form.get("cantidad"))
    except:
        return "Datos inválidos"

    col_codigo = buscar_columna(df, ["CODIGO"])
    col_nombre = buscar_columna(df, ["NOMBRE"])
    col_precio = buscar_columna(df, ["COSTO"])
    col_stock = buscar_columna(df, ["STOCK"])

    fila = df[
        (df[col_codigo].astype(str).str.upper() == busqueda) |
        (df[col_nombre].astype(str).str.upper().str.contains(busqueda, na=False))
    ]

    if fila.empty:
        return "Producto no encontrado"

    producto = fila.iloc[0]

    precio = float(str(producto[col_precio]).replace("S/", "").strip())
    stock = float(producto[col_stock])

    if stock < cantidad:
        return "Stock insuficiente"

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
# 🚀 RUN
# =============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)