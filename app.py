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
        print("ERROR CONECTANDO DB:", e)
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
    columnas = [
        "CODIGO", "NOMBRE DEL PRODUCTO", "EDITORIAL", "CATEGORIA",
        "COMPRAS", "VENTAS", "STOCK", "COSTO UNITARIO",
        "PRECIO DE VENTA", "UTILIDAD PROD", "VALOR DEL INVENTARIO"
    ]

    conn = get_conn()
    if not conn:
        return pd.DataFrame(columns=columnas)

    try:
        df = pd.read_sql("""
            SELECT
                codigo AS "CODIGO",
                nombre AS "NOMBRE DEL PRODUCTO",
                editorial AS "EDITORIAL",
                categoria AS "CATEGORIA",
                compras AS "COMPRAS",
                ventas AS "VENTAS",
                stock AS "STOCK",
                costo_unitario AS "COSTO UNITARIO",
                precio_venta AS "PRECIO DE VENTA",
                utilidad_prod AS "UTILIDAD PROD",
                valor_inventario AS "VALOR DEL INVENTARIO"
            FROM inventario
            ORDER BY codigo ASC
        """, conn)
    except Exception as e:
        print("ERROR LEYENDO INVENTARIO DB:", e)
        df = pd.DataFrame(columns=columnas)
    finally:
        conn.close()

    df = df.fillna("")
    return df


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

    editoriales = [x for x in editoriales if x.strip()]
    categorias = [x for x in categorias if x.strip()]

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


def buscar_producto(busqueda):
    conn = get_conn()
    if not conn:
        return None

    cur = conn.cursor()
    busqueda_limpia = limpiar(busqueda)

    try:
        cur.execute("""
            SELECT codigo, nombre, editorial, categoria, compras, ventas, stock,
                   costo_unitario, precio_venta, utilidad_prod, valor_inventario
            FROM inventario
            WHERE UPPER(codigo) = %s OR UPPER(nombre) = %s
            LIMIT 1
        """, (busqueda_limpia, busqueda_limpia))

        producto = cur.fetchone()

        if not producto:
            patron = f"%{busqueda_limpia}%"
            cur.execute("""
                SELECT codigo, nombre, editorial, categoria, compras, ventas, stock,
                       costo_unitario, precio_venta, utilidad_prod, valor_inventario
                FROM inventario
                WHERE UPPER(codigo) LIKE %s OR UPPER(nombre) LIKE %s
                ORDER BY codigo ASC
                LIMIT 1
            """, (patron, patron))
            producto = cur.fetchone()

        if not producto:
            return None

        return {
            "codigo": producto[0],
            "nombre": producto[1],
            "editorial": producto[2],
            "categoria": producto[3],
            "compras": producto[4],
            "ventas": producto[5],
            "stock": producto[6],
            "costo_unitario": producto[7],
            "precio_venta": producto[8],
            "utilidad_prod": producto[9],
            "valor_inventario": producto[10]
        }

    except Exception as e:
        print("ERROR BUSCANDO PRODUCTO:", e)
        return None

    finally:
        cur.close()
        conn.close()


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("usuario", "").strip().lower()
        password = request.form.get("password")

        if user in USUARIOS and USUARIOS[user]["password"] == password:
            session["user"] = user
            session["rol"] = USUARIOS[user]["rol"]
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
        rol=session.get("rol"),
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

    if not es_admin():
        return redirect("/")

    df_original = cargar_excel()
    df = aplicar_filtros(df_original)

    editoriales, categorias, sugerencias = opciones_filtros(df_original)

    libros_inventario = []

    for _, row in df_original.iterrows():
        libros_inventario.append({
            "codigo": str(row["CODIGO"]).strip(),
            "nombre": str(row["NOMBRE DEL PRODUCTO"]).strip(),
            "stock": int(row["STOCK"] or 0),
            "precio": float(row["COSTO UNITARIO"] or 0)
        })

    return render_template(
        "inventario.html",
        tabla=df.to_html(index=False, classes="tabla"),
        usuario=session.get("user"),
        rol=session.get("rol"),
        editoriales=editoriales,
        categorias=categorias,
        sugerencias=sugerencias,
        libros_inventario=libros_inventario,
        editoriales_seleccionadas=request.args.getlist("editorial"),
        categorias_seleccionadas=request.args.getlist("categoria")
    )


@app.route("/descargar_inventario")
def descargar_inventario():
    if login_requerido():
        return redirect("/login")

    if not es_admin():
        return redirect("/")

    df = cargar_excel()

    archivo = BytesIO()
    df.to_excel(archivo, index=False)
    archivo.seek(0)

    return send_file(
        archivo,
        as_attachment=True,
        download_name="inventario.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.route("/inventario/agregar", methods=["POST"])
def agregar_producto():
    if login_requerido():
        return redirect("/login")

    if not es_admin():
        return redirect("/")

    codigo = limpiar(request.form.get("codigo"))
    nombre = request.form.get("nombre")

    if not codigo or not nombre:
        return redirect("/inventario")

    compras = numero(request.form.get("compras"), int)
    ventas = numero(request.form.get("ventas"), int)
    stock = numero(request.form.get("stock"), int)

    costo = numero(
        request.form.get("costo") or request.form.get("costo_unitario") or request.form.get("precio"),
        float
    )
    precio = numero(request.form.get("precio_venta") or request.form.get("precio"), float)

    utilidad = precio - costo
    valor = stock * costo

    conn = get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO inventario (
                    codigo, nombre, editorial, categoria,
                    compras, ventas, stock,
                    costo_unitario, precio_venta,
                    utilidad_prod, valor_inventario
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (codigo) DO UPDATE SET
                    nombre = EXCLUDED.nombre,
                    editorial = EXCLUDED.editorial,
                    categoria = EXCLUDED.categoria,
                    compras = EXCLUDED.compras,
                    ventas = EXCLUDED.ventas,
                    stock = EXCLUDED.stock,
                    costo_unitario = EXCLUDED.costo_unitario,
                    precio_venta = EXCLUDED.precio_venta,
                    utilidad_prod = EXCLUDED.utilidad_prod,
                    valor_inventario = EXCLUDED.valor_inventario
            """, (
                codigo,
                nombre,
                request.form.get("editorial") or "",
                request.form.get("categoria") or "",
                compras,
                ventas,
                stock,
                costo,
                precio,
                utilidad,
                valor
            ))

            conn.commit()
            cur.close()
        except Exception as e:
            print("ERROR AGREGANDO PRODUCTO DB:", e)
        finally:
            conn.close()

    return redirect("/inventario")


@app.route("/inventario/editar", methods=["POST"])
@app.route("/inventario/actualizar", methods=["POST"])
@app.route("/inventario/stock", methods=["POST"])
@app.route("/inventario/actualizar_stock", methods=["POST"])
def actualizar_producto():
    if login_requerido():
        return redirect("/login")

    if not es_admin():
        return redirect("/")

    busqueda = limpiar(request.form.get("codigo"))

    if not busqueda:
        return redirect("/inventario")

    producto = buscar_producto(busqueda)

    if not producto:
        return redirect("/inventario")

    codigo = producto["codigo"]

    nombre = request.form.get("nombre") or producto["nombre"]
    editorial = request.form.get("editorial") or producto["editorial"]
    categoria = request.form.get("categoria") or producto["categoria"]

    compras = producto["compras"] or 0
    ventas = producto["ventas"] or 0
    stock = producto["stock"] or 0
    costo = producto["costo_unitario"] or 0
    precio = producto["precio_venta"] or 0

    if request.form.get("compras") not in [None, ""]:
        compras = numero(request.form.get("compras"), int)

    if request.form.get("ventas") not in [None, ""]:
        ventas = numero(request.form.get("ventas"), int)

    if request.form.get("stock") not in [None, ""]:
        stock = numero(request.form.get("stock"), int)

    if request.form.get("nuevo_stock") not in [None, ""]:
        stock = numero(request.form.get("nuevo_stock"), int)

    if request.form.get("cantidad") not in [None, ""]:
        stock = stock + numero(request.form.get("cantidad"), int)

    if request.form.get("costo") not in [None, ""]:
        costo = numero(request.form.get("costo"), float)

    if request.form.get("costo_unitario") not in [None, ""]:
        costo = numero(request.form.get("costo_unitario"), float)

    if request.form.get("precio") not in [None, ""]:
        costo = numero(request.form.get("precio"), float)

    if request.form.get("precio_venta") not in [None, ""]:
        precio = numero(request.form.get("precio_venta"), float)

    utilidad = precio - costo
    valor = stock * costo

    conn = get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE inventario
                SET nombre = %s,
                    editorial = %s,
                    categoria = %s,
                    compras = %s,
                    ventas = %s,
                    stock = %s,
                    costo_unitario = %s,
                    precio_venta = %s,
                    utilidad_prod = %s,
                    valor_inventario = %s
                WHERE codigo = %s
            """, (
                nombre, editorial, categoria,
                compras, ventas, stock,
                costo, precio, utilidad, valor,
                codigo
            ))

            conn.commit()
            cur.close()
        except Exception as e:
            print("ERROR ACTUALIZANDO PRODUCTO DB:", e)
        finally:
            conn.close()

    return redirect("/inventario")


@app.route("/inventario/eliminar", methods=["POST"])
def eliminar_producto():
    if login_requerido():
        return redirect("/login")

    if not es_admin():
        return redirect("/")

    busqueda = limpiar(request.form.get("codigo"))
    producto = buscar_producto(busqueda)

    if producto:
        conn = get_conn()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM inventario WHERE codigo = %s", (producto["codigo"],))
                conn.commit()
                cur.close()
            except Exception as e:
                print("ERROR ELIMINANDO PRODUCTO DB:", e)
            finally:
                conn.close()

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

    carrito = session.get("carrito", [])

    busqueda = limpiar(request.form.get("codigo"))
    cantidad = numero(request.form.get("cantidad"), int)

    if not busqueda or cantidad <= 0:
        return redirect("/")

    item = buscar_producto(busqueda)

    if not item:
        return redirect("/")

    stock_actual = numero(item["stock"], int)

    if cantidad > stock_actual:
        return redirect("/")

    precio = numero(item["costo_unitario"], float)

    carrito.append({
        "codigo": item["codigo"],
        "nombre": item["nombre"],
        "precio": precio,
        "cantidad": cantidad,
        "subtotal": precio * cantidad
    })

    session["carrito"] = carrito
    return redirect("/")


@app.route("/finalizar/<metodo>")
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
    ahora = hora_peru()

    try:
        for item in carrito:
            codigo = limpiar(item["codigo"])
            cantidad = numero(item["cantidad"], int)

            cur.execute("""
                SELECT stock, ventas, costo_unitario
                FROM inventario
                WHERE UPPER(codigo) = %s
            """, (codigo,))

            producto = cur.fetchone()

            if not producto:
                conn.rollback()
                return redirect("/")

            stock_actual = producto[0] or 0
            ventas_actuales = producto[1] or 0
            costo = producto[2] or 0

            if cantidad > stock_actual:
                conn.rollback()
                return redirect("/")

            nuevo_stock = stock_actual - cantidad
            nuevas_ventas = ventas_actuales + cantidad
            nuevo_valor = nuevo_stock * costo

            cur.execute("""
                UPDATE inventario
                SET stock = %s,
                    ventas = %s,
                    valor_inventario = %s
                WHERE UPPER(codigo) = %s
            """, (nuevo_stock, nuevas_ventas, nuevo_valor, codigo))

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
        print("ERROR FINALIZANDO VENTA:", e)
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
            usuario=session.get("user"),
            rol=session.get("rol"),
            inicio=request.args.get("inicio", ""),
            fin=request.args.get("fin", ""),
            filtro_usuario=request.args.get("usuario", ""),
            filtro_metodo=request.args.get("metodo", "")
        )

    df.columns = df.columns.str.lower()
    df["subtotal"] = pd.to_numeric(df["subtotal"], errors="coerce").fillna(0)
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
    df["metodo"] = df["metodo"].astype(str).str.upper()

    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")

    df = df.reset_index(drop=True)
    df.insert(0, "numero_venta", range(1, len(df) + 1))

    total = df["subtotal"].sum()
    total_efectivo = df[df["metodo"] == "EFECTIVO"]["subtotal"].sum()
    total_yape = df[df["metodo"] == "YAPE"]["subtotal"].sum()
    cantidad_ventas = len(df)
    productos_vendidos = int(df["cantidad"].sum())
    ticket_promedio = total / cantidad_ventas if cantidad_ventas > 0 else 0

    producto_top = "Sin datos"
    vendedor_top = "Sin datos"

    try:
        producto_top = df.groupby("nombre")["cantidad"].sum().sort_values(ascending=False).index[0]
    except:
        pass

    try:
        vendedor_top = df.groupby("usuario")["subtotal"].sum().sort_values(ascending=False).index[0]
    except:
        pass

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
        usuario=session.get("user"),
        rol=session.get("rol"),
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

    if conn:
        cur = conn.cursor()

        try:
            cur.execute("SELECT codigo, cantidad FROM ventas WHERE id = %s", (id,))
            venta = cur.fetchone()

            if venta:
                codigo_venta = limpiar(venta[0])
                cantidad_venta = numero(venta[1], int)

                cur.execute("""
                    SELECT stock, ventas, costo_unitario
                    FROM inventario
                    WHERE UPPER(codigo) = %s
                """, (codigo_venta,))

                producto = cur.fetchone()

                if producto:
                    stock_actual = producto[0] or 0
                    ventas_actuales = producto[1] or 0
                    costo = producto[2] or 0

                    nuevo_stock = stock_actual + cantidad_venta
                    nuevas_ventas = max(0, ventas_actuales - cantidad_venta)
                    nuevo_valor = nuevo_stock * costo

                    cur.execute("""
                        UPDATE inventario
                        SET stock = %s,
                            ventas = %s,
                            valor_inventario = %s
                        WHERE UPPER(codigo) = %s
                    """, (nuevo_stock, nuevas_ventas, nuevo_valor, codigo_venta))

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