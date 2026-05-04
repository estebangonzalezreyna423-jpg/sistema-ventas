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
        "stock": p[2] or 0,
        "costo_unitario": p[3] or 0
    }


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

@app.route("/inventario")
def inventario():
    if login_requerido():
        return redirect("/login")

    if not es_admin():
        return redirect("/")

    df = cargar_excel()

    tabla = ""
    editoriales = []
    categorias = []
    sugerencias = []
    libros_inventario = []

    if not df.empty:
        if "editorial" in df.columns:
            editoriales = sorted(df["editorial"].dropna().astype(str).unique())

        if "categoria" in df.columns:
            categorias = sorted(df["categoria"].dropna().astype(str).unique())

        for _, row in df.iterrows():
            codigo = str(row["codigo"]).strip()
            nombre = str(row["nombre"]).strip()

            sugerencias.append(codigo)
            sugerencias.append(nombre)

            libros_inventario.append({
                "codigo": codigo,
                "nombre": nombre,
                "stock": int(row["stock"] or 0),
                "precio": float(row["costo_unitario"] or 0)
            })

        sugerencias = sorted(list(set(sugerencias)))
        tabla = df.to_html(index=False, classes="tabla")

    return render_template(
        "inventario.html",
        tabla=tabla,
        usuario=session["user"],
        rol=session["rol"],
        editoriales=editoriales,
        categorias=categorias,
        sugerencias=sugerencias,
        libros_inventario=libros_inventario
    )

@app.route("/eliminar/<int:index>")
def eliminar(index):
    if login_requerido():
        return redirect("/login")

    carrito = session.get("carrito", [])

    if 0 <= index < len(carrito):
        carrito.pop(index)

    session["carrito"] = carrito
    return redirect("/")


@app.route("/agregar", methods=["POST"])
def agregar():
    if login_requerido():
        return redirect("/login")

    carrito = session.get("carrito", [])

    codigo = request.form.get("codigo")
    cantidad = numero(request.form.get("cantidad"), int)

    if cantidad <= 0:
        return redirect("/")

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
    print("FECHA RECIBIDA:", fecha_manual)

    if fecha_manual and fecha_manual.strip() != "":
       try:
           fecha_venta = datetime.strptime(fecha_manual, "%Y-%m-%dT%H:%M")
       except Exception as e:
           print("ERROR PARSEANDO FECHA:", e)
           fecha_venta = hora_peru()
    else:
        fecha_venta = hora_peru()

    try:
        for item in carrito:
            codigo = limpiar(item["codigo"])
            cantidad = int(item["cantidad"])

            cur.execute("""
                SELECT stock, ventas
                FROM inventario
                WHERE UPPER(codigo) = %s
            """, (codigo,))

            prod = cur.fetchone()

            if not prod:
                conn.rollback()
                return redirect("/")

            stock_actual = prod[0] or 0
            ventas_actuales = prod[1] or 0

            if cantidad > stock_actual:
                conn.rollback()
                return redirect("/")

            nuevo_stock = stock_actual - cantidad
            nuevas_ventas = ventas_actuales + cantidad

            cur.execute("""
                UPDATE inventario
                SET stock = %s, ventas = %s
                WHERE UPPER(codigo) = %s
            """, (nuevo_stock, nuevas_ventas, codigo))

            cur.execute("""
                INSERT INTO ventas 
                (usuario, codigo, nombre, cantidad, subtotal, metodo, fecha)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (
                session["user"],
                codigo,
                item["nombre"],
                cantidad,
                item["subtotal"],
                metodo.upper(),
                fecha_venta
            ))

        conn.commit()

    except Exception as e:
        print("ERROR GUARDANDO VENTA:", e)
        conn.rollback()

    finally:
        cur.close()
        conn.close()

    session["carrito"] = []
    return redirect("/")


def obtener_ventas_filtradas():
    conn = get_conn()

    if not conn:
        return pd.DataFrame()

    inicio = request.args.get("inicio")
    fin = request.args.get("fin")
    usuario = request.args.get("usuario")
    metodo = request.args.get("metodo")

    query = "SELECT * FROM ventas WHERE 1=1"
    params = []

    if inicio:
        query += " AND fecha >= %s"
        params.append(inicio)

    if fin:
        try:
            fin_dt = datetime.strptime(fin, "%Y-%m-%d") + timedelta(days=1)
            query += " AND fecha < %s"
            params.append(fin_dt.strftime("%Y-%m-%d"))
        except:
            pass

    if usuario:
        query += " AND UPPER(usuario) = %s"
        params.append(usuario.upper())

    if metodo:
        query += " AND UPPER(metodo) = %s"
        params.append(metodo.upper())

    query += " ORDER BY fecha DESC"

    df = pd.read_sql(query, conn, params=params)
    conn.close()

    return df


@app.route("/ventas")
def ventas():
    if login_requerido():
        return redirect("/login")

    df = obtener_ventas_filtradas()

    if df.empty:
        return render_template(
            "ventas.html",
            ventas=[],
            total=0,
            total_efectivo=0,
            total_yape=0,
            cantidad_ventas=0,
            productos_vendidos=0,
            ticket_promedio=0,
            producto_top="Sin datos",
            vendedor_top="Sin datos",
            usuario=session["user"],
            rol=session["rol"],
            inicio=request.args.get("inicio", ""),
            fin=request.args.get("fin", ""),
            filtro_usuario=request.args.get("usuario", ""),
            filtro_metodo=request.args.get("metodo", "")
        )

    df["subtotal"] = pd.to_numeric(df["subtotal"], errors="coerce").fillna(0)
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
    df["metodo"] = df["metodo"].astype(str).str.upper()

    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["fecha"] = df["fecha"].dt.strftime("%d/%m/%Y %H:%M:%S")

    df = df.reset_index(drop=True)
    df.insert(0, "numero_venta", range(1, len(df) + 1))

    total = df["subtotal"].sum()
    total_efectivo = df[df["metodo"] == "EFECTIVO"]["subtotal"].sum()
    total_yape = df[df["metodo"] == "YAPE"]["subtotal"].sum()
    cantidad_ventas = len(df)
    productos_vendidos = int(df["cantidad"].sum())
    ticket_promedio = total / cantidad_ventas if cantidad_ventas > 0 else 0

    try:
        producto_top = df.groupby("nombre")["cantidad"].sum().sort_values(ascending=False).index[0]
    except:
        producto_top = "Sin datos"

    try:
        vendedor_top = df.groupby("usuario")["subtotal"].sum().sort_values(ascending=False).index[0]
    except:
        vendedor_top = "Sin datos"

    return render_template(
        "ventas.html",
        ventas=df.to_dict(orient="records"),
        total=round(total, 2),
        total_efectivo=round(total_efectivo, 2),
        total_yape=round(total_yape, 2),
        cantidad_ventas=cantidad_ventas,
        productos_vendidos=productos_vendidos,
        ticket_promedio=round(ticket_promedio, 2),
        producto_top=producto_top,
        vendedor_top=vendedor_top,
        usuario=session["user"],
        rol=session["rol"],
        inicio=request.args.get("inicio", ""),
        fin=request.args.get("fin", ""),
        filtro_usuario=request.args.get("usuario", ""),
        filtro_metodo=request.args.get("metodo", "")
    )


@app.route("/descargar_ventas")
def descargar_ventas():
    if login_requerido():
        return redirect("/login")

    df = obtener_ventas_filtradas()

    archivo = BytesIO()
    df.to_excel(archivo, index=False)
    archivo.seek(0)

    return send_file(
        archivo,
        as_attachment=True,
        download_name="ventas.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.route("/ventas/eliminar/<int:id>")
def eliminar_venta(id):
    if login_requerido():
        return redirect("/login")

    if not es_admin():
        return redirect("/ventas")

    conn = get_conn()
    if not conn:
        return redirect("/ventas")

    cur = conn.cursor()

    try:
        cur.execute("SELECT codigo, cantidad FROM ventas WHERE id = %s", (id,))
        venta = cur.fetchone()

        if venta:
            codigo = limpiar(venta[0])
            cantidad = int(venta[1])

            cur.execute("""
                SELECT stock, ventas
                FROM inventario
                WHERE UPPER(codigo) = %s
            """, (codigo,))

            producto = cur.fetchone()

            if producto:
                stock_actual = producto[0] or 0
                ventas_actuales = producto[1] or 0

                nuevo_stock = stock_actual + cantidad
                nuevas_ventas = max(0, ventas_actuales - cantidad)

                cur.execute("""
                    UPDATE inventario
                    SET stock = %s, ventas = %s
                    WHERE UPPER(codigo) = %s
                """, (nuevo_stock, nuevas_ventas, codigo))

            cur.execute("DELETE FROM ventas WHERE id = %s", (id,))
            conn.commit()

    except Exception as e:
        print("ERROR ELIMINANDO VENTA:", e)
        conn.rollback()

    finally:
        cur.close()
        conn.close()

    return redirect("/ventas")


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)