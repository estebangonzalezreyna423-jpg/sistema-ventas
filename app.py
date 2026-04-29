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

    editoriales = [e.upper() for e in editoriales if e.strip()]
    categorias = [c.upper() for c in categorias if c.strip()]

    if editoriales:
        df = df[df["EDITORIAL"].astype(str).str.upper().isin(editoriales)]

    if categorias:
        df = df[df["CATEGORIA"].astype(str).str.upper().isin(categorias)]

    return df


def opciones_filtros(df):
    editoriales = sorted(df["EDITORIAL"].dropna().astype(str).unique())
    categorias = sorted(df["CATEGORIA"].dropna().astype(str).unique())

    editoriales = [x for x in editoriales if x.strip() != ""]
    categorias = [x for x in categorias if x.strip() != ""]

    sugerencias = []

    for _, row in df.iterrows():
        codigo = str(row["CODIGO"]).strip()
        nombre = str(row["NOMBRE DEL PRODUCTO"]).strip()

        if codigo:
            sugerencias.append(codigo)

        if nombre:
            sugerencias.append(nombre)

    sugerencias = sorted(list(set(sugerencias)))

    return editoriales, categorias, sugerencias


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


@app.route("/")
def index():
    if login_requerido():
        return redirect("/login")

    df_original = cargar_excel()
    df = aplicar_filtros(df_original)

    carrito = session.get("carrito", [])
    total = sum(i["subtotal"] for i in carrito)

    editoriales, categorias, sugerencias = opciones_filtros(df_original)

    return render_template(
        "index.html",
        tabla=df.to_html(index=False, classes="tabla"),
        carrito=carrito,
        total=round(total, 2),
        usuario=session.get("user"),
        editoriales=editoriales,
        categorias=categorias,
        sugerencias=sugerencias,
        editoriales_seleccionadas=request.args.getlist("editorial"),
        categorias_seleccionadas=request.args.getlist("categoria")
    )


@app.route("/inventario")
def inventario():
    if login_requerido():
        return redirect("/login")

    if session.get("user") != "PC1":
        return redirect("/")

    df_original = cargar_excel()
    df = aplicar_filtros(df_original)

    editoriales, categorias, sugerencias = opciones_filtros(df_original)

    return render_template(
        "inventario.html",
        tabla=df.to_html(index=False, classes="tabla"),
        usuario=session.get("user"),
        editoriales=editoriales,
        categorias=categorias,
        sugerencias=sugerencias,
        editoriales_seleccionadas=request.args.getlist("editorial"),
        categorias_seleccionadas=request.args.getlist("categoria")
    )


@app.route("/inventario/agregar", methods=["POST"])
def agregar_producto():
    if login_requerido():
        return redirect("/login")

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
            "UTILIDAD PROD": precio - costo,
            "VALOR DEL INVENTARIO": stock * costo
        }

        df = pd.concat([df, pd.DataFrame([nuevo])], ignore_index=True)
        guardar_excel(df)

    except:
        pass

    return redirect("/inventario")


@app.route("/inventario/eliminar", methods=["POST"])
def eliminar_producto():
    if login_requerido():
        return redirect("/login")

    if session.get("user") != "PC1":
        return redirect("/")

    df = cargar_excel()
    codigo = limpiar(request.form.get("codigo"))

    if codigo:
        df = df[df["CODIGO"].astype(str).str.upper() != codigo]
        guardar_excel(df)

    return redirect("/inventario")


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

    busqueda = limpiar(request.form.get("codigo"))
    cantidad = int(request.form.get("cantidad") or 0)

    if not busqueda or cantidad <= 0:
        return redirect("/")

    fila = df[
        (df["CODIGO"].astype(str).str.upper() == busqueda) |
        (df["NOMBRE DEL PRODUCTO"].astype(str).str.upper() == busqueda)
    ]

    if fila.empty:
        fila = df[
            df["CODIGO"].astype(str).str.upper().str.contains(busqueda, na=False) |
            df["NOMBRE DEL PRODUCTO"].astype(str).str.upper().str.contains(busqueda, na=False)
        ]

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
            nuevas_ventas = ventas_actuales + item["cantidad"]

            df.at[i, "STOCK"] = nuevo_stock
            df.at[i, "VENTAS"] = nuevas_ventas
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


@app.route("/ventas")
def ventas():
    if login_requerido():
        return redirect("/login")

    conn = get_conn()

    if not conn:
        return render_template(
            "ventas.html",
            ventas=[],
            total=0,
            total_efectivo=0,
            total_yape=0,
            usuario=session.get("user")
        )

    df = pd.read_sql("SELECT * FROM ventas ORDER BY fecha DESC", conn)
    conn.close()

    df.columns = df.columns.str.lower()

    if df.empty:
        total = 0
        total_efectivo = 0
        total_yape = 0
    else:
        df["subtotal"] = pd.to_numeric(df["subtotal"], errors="coerce").fillna(0)
        df["metodo"] = df["metodo"].astype(str).str.upper()

        total = df["subtotal"].sum()
        total_efectivo = df[df["metodo"] == "EFECTIVO"]["subtotal"].sum()
        total_yape = df[df["metodo"] == "YAPE"]["subtotal"].sum()

    return render_template(
        "ventas.html",
        ventas=df.to_dict(orient="records"),
        total=round(total, 2),
        total_efectivo=round(total_efectivo, 2),
        total_yape=round(total_yape, 2),
        usuario=session.get("user")
    )


@app.route("/ventas/eliminar/<int:id>")
def eliminar_venta(id):
    if login_requerido():
        return redirect("/login")

    if session.get("user") != "PC1":
        return redirect("/ventas")

    conn = get_conn()

    if conn:
        cur = conn.cursor()

        cur.execute("SELECT codigo, cantidad FROM ventas WHERE id = %s", (id,))
        venta = cur.fetchone()

        if venta:
            codigo_venta = limpiar(venta[0])
            cantidad_venta = int(venta[1])

            df = cargar_excel()
            idx = df[df["CODIGO"].astype(str).str.upper() == codigo_venta].index

            if len(idx) > 0:
                i = idx[0]

                stock_actual = int(df.at[i, "STOCK"] or 0)
                ventas_actuales = int(df.at[i, "VENTAS"] or 0)
                costo = float(df.at[i, "COSTO UNITARIO"] or 0)

                nuevo_stock = stock_actual + cantidad_venta
                nuevas_ventas = max(0, ventas_actuales - cantidad_venta)

                df.at[i, "STOCK"] = nuevo_stock
                df.at[i, "VENTAS"] = nuevas_ventas
                df.at[i, "VALOR DEL INVENTARIO"] = nuevo_stock * costo

                guardar_excel(df)

            cur.execute("DELETE FROM ventas WHERE id = %s", (id,))
            conn.commit()

        cur.close()
        conn.close()

    return redirect("/ventas")


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)