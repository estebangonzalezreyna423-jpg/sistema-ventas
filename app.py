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

def cargar_excel():
    if not os.path.exists(ARCHIVO):
        print("❌ No existe inventario.xlsx")
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
# 🏠 INDEX (FILTROS)
# =============================

@app.route("/")
def index():
    if login_requerido():
        return redirect("/login")

    df = cargar_excel()
    if df.empty:
        return "❌ No hay inventario cargado"

    carrito = session.get("carrito", [])
    total = sum(item["subtotal"] for item in carrito)

    col_editorial = buscar_columna(df, ["EDITORIAL"])
    col_categoria = buscar_columna(df, ["CATEGORIA"])

    editoriales = sorted(df[col_editorial].dropna().astype(str).str.upper().unique()) if col_editorial else []
    categorias = sorted(df[col_categoria].dropna().astype(str).str.upper().unique()) if col_categoria else []

    editorial_filtro = limpiar_texto(request.args.get("editorial"))
    categoria_filtro = limpiar_texto(request.args.get("categoria"))

    df_filtrado = df.copy()

    if editorial_filtro and col_editorial:
        df_filtrado = df_filtrado[df_filtrado[col_editorial].astype(str).str.upper() == editorial_filtro]

    if categoria_filtro and col_categoria:
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
# ➕ AGREGAR
# =============================

@app.route("/agregar", methods=["POST"])
def agregar():
    if login_requerido():
        return redirect("/login")

    df = cargar_excel()
    if df.empty:
        return redirect("/")

    carrito = session.get("carrito", [])

    codigo = limpiar_texto(request.form.get("codigo"))
    cantidad = request.form.get("cantidad")

    if not codigo or not cantidad:
        return redirect("/")

    try:
        cantidad = int(cantidad)
    except:
        return redirect("/")

    col_codigo = buscar_columna(df, ["CODIGO"])
    col_nombre = buscar_columna(df, ["NOMBRE"])
    col_precio = buscar_columna(df, ["COSTO"])
    col_stock = buscar_columna(df, ["STOCK"])

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
# ❌ ELIMINAR
# =============================

@app.route("/eliminar/<int:index>")
def eliminar(index):
    if login_requerido():
        return redirect("/login")

    carrito = session.get("carrito", [])

    if 0 <= index < len(carrito):
        carrito.pop(index)

    session["carrito"] = carrito
    return redirect("/")


# =============================
# 💰 FINALIZAR
# =============================

@app.route("/finalizar/<metodo>")
def finalizar(metodo):
    if login_requerido():
        return redirect("/login")

    carrito = session.get("carrito", [])
    if not carrito:
        return redirect("/")

    df = cargar_excel()
    if df.empty:
        return redirect("/")

    col_codigo = buscar_columna(df, ["CODIGO"])
    col_stock = buscar_columna(df, ["STOCK"])
    col_nombre = buscar_columna(df, ["NOMBRE"])
    col_ventas = buscar_columna(df, ["VENTA"])  # 🔥 CLAVE

    ahora = datetime.now()

    ventas = []

    for item in carrito:
        fila = df[df[col_codigo] == item["codigo"]].index

        if len(fila) > 0:
            i = fila[0]

            # 🔻 STOCK
            df.at[i, col_stock] -= item["cantidad"]

            # 🔥 SUMAR VENTAS
            if col_ventas:
                actual = df.at[i, col_ventas]
                try:
                    df.at[i, col_ventas] = (actual if pd.notna(actual) else 0) + item["cantidad"]
                except:
                    df.at[i, col_ventas] = item["cantidad"]

            ventas.append({
                "USUARIO": session["user"],
                "CODIGO": item["codigo"],
                "NOMBRE": df.at[i, col_nombre] if col_nombre else "",
                "CANTIDAD": item["cantidad"],
                "SUBTOTAL": item["subtotal"],
                "METODO": metodo.upper(),
                "FECHA": ahora.strftime("%Y-%m-%d %H:%M:%S"),
                "MES": ahora.strftime("%m"),
                "AÑO": ahora.strftime("%Y")
            })

    # 💾 INVENTARIO
    df.to_excel(ARCHIVO, index=False)

    # 💾 VENTAS
    df_ventas = pd.DataFrame(ventas)

    if os.path.exists(ARCHIVO_VENTAS):
        df_existente = pd.read_excel(ARCHIVO_VENTAS)
        df_ventas = pd.concat([df_existente, df_ventas], ignore_index=True)

    df_ventas.to_excel(ARCHIVO_VENTAS, index=False)

    session["carrito"] = []

    return redirect("/")


# =============================
# 🚀 RUN
# =============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)