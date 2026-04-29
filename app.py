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
        "CODIGO",
        "NOMBRE DEL PRODUCTO",
        "EDITORIAL",
        "CATEGORIA",
        "COMPRAS",
        "VENTAS",
        "STOCK",
        "COSTO UNITARIO",
        "PRECIO DE VENTA",
        "UTILIDAD PROD",
        "VALOR DEL INVENTARIO"
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
    editorial = request.args.get("editorial", "")
    categoria = request.args.get("categoria", "")
    buscar = request.args.get("buscar", "")

    if editorial:
        df = df[df["EDITORIAL"].astype(str).str.upper() == editorial.upper()]

    if categoria:
        df = df[df["CATEGORIA"].astype(str).str.upper() == categoria.upper()]

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

    df_original = cargar_excel()
    df = aplicar_filtros(df_original)

    carrito = session.get("carrito", [])
    total = sum(i["subtotal"] for i in carrito)

    editoriales = sorted(df_original["EDITORIAL"].dropna().astype(str).unique())
    categorias = sorted(df_original["CATEGORIA"].dropna().astype(str).unique())

    editoriales = [x for x in editoriales if x.strip() != ""]
    categorias = [x for x in categorias if x.strip() != ""]

    return render_template(
        "index.html",
        tabla=df.to_html(index=False, classes="tabla"),
        carrito=carrito,
        total=total,
        usuario=session.get("user"),
        editoriales=editoriales,
        categorias=categorias
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

    df_original = cargar_excel()
    df = aplicar_filtros(df_original)

    editoriales = sorted(df_original["EDITORIAL"].dropna().astype(str).unique())
    categorias = sorted(df_original["CATEGORIA"].dropna().astype(str).unique())

    editoriales = [x for x in editoriales if x.strip() != ""]
    categorias = [x for x in categorias if x.strip() != ""]

    return render_template(
        "inventario.html",
        tabla=df.to_html(index=False, classes="tabla"),
        usuario=session.get("user"),
        editoriales=editoriales,
        categorias=categorias
    )


# =============================
# AGREGAR PRODUCTO
# =============================
@app.route("/inventario/agregar", methods=["POST"])
def agregar_producto():
    if session.get("user") != "PC1":
        return redirect("/")

    df = cargar_excel()

    codigo = limpiar(request.form.get("codigo"))
    nombre = request.form.get("nombre")

    if not codigo or not nombre:
        return redirect("/inventario")

    try:
        compras = int(request.form.get("compras") or 0)
        ventas = int(request.form.get("ventas") or 0)
        stock = int(request.form.get("stock") or (compras - ventas))

        costo = float(request.form.get("costo") or request.form.get("costo_unitario") or 0)
        precio = float(request.form.get("precio") or request.form.get("precio_venta") or 0)

        utilidad = precio - costo
        valor_inventario = stock * costo

        nuevo = {
            "CODIGO": codigo,
            "NOMBRE DEL PRODUCTO": nombre,
            "EDITORIAL": request.form.get("editorial") or "",
            "CATEGORIA": request.form.get("categoria") or "",
            "COMPRAS": compras,
            "VENTAS": ventas,
            "STOCK": stock,
            "COSTO UNITARIO": costo,
            "PRECIO DE VENTA": precio,
            "UTILIDAD PROD": utilidad,
            "VALOR DEL INVENTARIO": valor_inventario
        }

        df = pd.concat([df, pd.DataFrame([nuevo])], ignore_index=True)
        guardar_excel(df)

    except:
        pass

    return redirect("/inventario")


# =============================
# ACTUALIZAR PRODUCTO
# =============================
@app.route("/inventario/actualizar", methods=["POST"])
def actualizar_producto():
    if session.get("user") != "PC1":
        return redirect("/")

    df = cargar_excel()
    codigo = limpiar(request.form.get("codigo"))

    idx = df[df["CODIGO"].astype(str).str.upper() == codigo].index

    if len(idx) > 0:
        i = idx[0]

        try:
            if request.form.get("nombre"):
                df.at[i, "NOMBRE DEL PRODUCTO"] = request.form.get("nombre")

            if request.form.get("editorial"):
                df.at[i, "EDITORIAL"] = request.form.get("editorial")

            if request.form.get("categoria"):
                df.at[i, "CATEGORIA"] = request.form.get("categoria")

            if request.form.get("compras"):
                df.at[i, "COMPRAS"] = int(request.form.get("compras"))

            if request.form.get("ventas"):
                df.at[i, "VENTAS"] = int(request.form.get("ventas"))

            if request.form.get("stock"):
                df.at[i, "STOCK"] = int(request.form.get("stock"))

            if request.form.get("costo") or request.form.get("costo_unitario"):
                df.at[i, "COSTO UNITARIO"] = float(request.form.get("costo") or request.form.get("costo_unitario"))

            if request.form.get("precio") or request.form.get("precio_venta"):
                df.at[i, "PRECIO DE VENTA"] = float(request.form.get("precio") or request.form.get("precio_venta"))

            costo = float(df.at[i, "COSTO UNITARIO"] or 0)
            precio = float(df.at[i, "PRECIO DE VENTA"] or 0)
            stock = int(df.at[i, "STOCK"] or 0)

            df.at[i, "UTILIDAD PROD"] = precio - costo
            df.at[i, "VALOR DEL INVENTARIO"] = stock * costo

            guardar_excel(df)

        except:
            pass

    return redirect("/inventario")


# =============================
# ELIMINAR PRODUCTO
# =============================
@app.route("/inventario/eliminar", methods=["POST"])
def eliminar_producto():
    if session.get("user") != "PC1":
        return redirect("/")

    df = cargar_excel()
    codigo = limpiar(request.form.get("codigo"))

    df = df[df["CODIGO"].astype(str).str.upper() != codigo]
    guardar_excel(df)

    return redirect("/inventario")


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

            stock_actual = int(df.at[i, "STOCK"] or 0)
            ventas_actuales = int(df.at[i, "VENTAS"] or 0)
            costo = float(df.at[i, "COSTO UNITARIO"] or 0)

            nuevo_stock = max(0, stock_actual - item["cantidad"])

            df.at[i, "STOCK"] = nuevo_stock
            df.at[i, "VENTAS"] = ventas_actuales + item["cantidad"]
            df.at[i, "VALOR DEL INVENTARIO"] = nuevo_stock * costo

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
# INIT
# =============================
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)