from flask import Flask, render_template, request, redirect, session, send_file
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
from io import BytesIO
from threading import Lock
from sqlalchemy import create_engine, text

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "clave_super_segura_123")

# Archivos Excel antiguos: solo se usarán para migrar datos iniciales si existen
INVENTARIO_FILE = "inventario.xlsx"
VENTAS_FILE = "ventas.xlsx"

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Falta configurar DATABASE_URL en Render > Environment")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
db_lock = Lock()

USUARIOS = {
    "admin": {"password": "Gladis26", "rol": "admin"},
    "oficina1": {"password": "Cepas1", "rol": "oficina"},
    "oficina2": {"password": "Cepas2", "rol": "oficina"},
    "biblioteca": {"password": "Biblioteca26", "rol": "biblioteca"}
}

COLUMNAS_INVENTARIO = [
    "codigo", "nombre", "editorial", "categoria",
    "compras", "ventas", "stock",
    "costo_unitario", "precio_venta",
    "utilidad_prod", "valor_inventario"
]

COLUMNAS_VENTAS = [
    "id", "usuario", "codigo", "nombre", "cantidad", "subtotal", "metodo", "fecha"
]


def limpiar(valor):
    return str(valor).strip().upper() if valor not in [None, ""] else ""


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
    except Exception:
        return 0


def normalizar_inventario(df):
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip().str.lower()

    renombrar = {
        "codigo": "codigo",
        "código": "codigo",
        "nombre del producto": "nombre",
        "producto": "nombre",
        "nombre": "nombre",
        "editorial": "editorial",
        "categoria": "categoria",
        "categoría": "categoria",
        "compras": "compras",
        "ventas": "ventas",
        "stock": "stock",
        "costo unitario": "costo_unitario",
        "costo_unitario": "costo_unitario",
        "precio venta": "precio_venta",
        "precio_venta": "precio_venta",
        "utilidad prod": "utilidad_prod",
        "utilidad_prod": "utilidad_prod",
        "valor inventario": "valor_inventario",
        "valor_inventario": "valor_inventario"
    }
    df = df.rename(columns={c: renombrar.get(c, c) for c in df.columns})

    for col in COLUMNAS_INVENTARIO:
        if col not in df.columns:
            df[col] = 0 if col in ["compras", "ventas", "stock", "costo_unitario", "precio_venta", "utilidad_prod", "valor_inventario"] else ""

    df = df[COLUMNAS_INVENTARIO].fillna("")
    df["codigo"] = df["codigo"].astype(str).str.strip().str.upper()
    df["nombre"] = df["nombre"].astype(str).str.strip()
    df["editorial"] = df["editorial"].astype(str).str.strip()
    df["categoria"] = df["categoria"].astype(str).str.strip()

    for col in ["compras", "ventas", "stock"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    for col in ["costo_unitario", "precio_venta", "utilidad_prod", "valor_inventario"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df = df[(df["codigo"] != "") & (df["codigo"].str.lower() != "nan")]
    df = df.drop_duplicates(subset=["codigo"], keep="last")
    df["valor_inventario"] = df["stock"] * df["costo_unitario"]
    return df.sort_values("codigo").reset_index(drop=True)


def normalizar_ventas(df):
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip().str.lower()

    renombrar = {
        "codigo": "codigo",
        "código": "codigo",
        "fecha": "fecha",
        "nombre": "nombre",
        "producto": "nombre",
        "cantidad": "cantidad",
        "subtotal": "subtotal",
        "metodo": "metodo",
        "método": "metodo",
        "usuario": "usuario",
        "id": "id"
    }

    df = df.rename(columns={c: renombrar.get(c, c) for c in df.columns})

    for col in COLUMNAS_VENTAS:
        if col not in df.columns:
            df[col] = "" if col not in ["id", "cantidad", "subtotal"] else 0

    df = df[COLUMNAS_VENTAS].fillna("")

    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0).astype(int)
    df["subtotal"] = pd.to_numeric(df["subtotal"], errors="coerce").fillna(0.0)
    df["metodo"] = df["metodo"].astype(str).str.upper()
    df["codigo"] = df["codigo"].astype(str).str.strip().str.upper()
    df["usuario"] = df["usuario"].astype(str).str.strip()
    df["nombre"] = df["nombre"].astype(str).str.strip()
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")

    # Si el Excel antiguo no tenía ID, se crean IDs únicos para poder eliminar ventas sin errores.
    ids = pd.to_numeric(df["id"], errors="coerce").fillna(0).astype(int)
    if (ids <= 0).any() or ids.duplicated().any():
        df["id"] = range(1, len(df) + 1)
    else:
        df["id"] = ids

    return df


def inicializar_bd():
    """Crea las tablas en PostgreSQL y migra desde Excel si la BD está vacía."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS inventario (
                codigo TEXT PRIMARY KEY,
                nombre TEXT,
                editorial TEXT,
                categoria TEXT,
                compras INTEGER DEFAULT 0,
                ventas INTEGER DEFAULT 0,
                stock INTEGER DEFAULT 0,
                costo_unitario NUMERIC(12,2) DEFAULT 0,
                precio_venta NUMERIC(12,2) DEFAULT 0,
                utilidad_prod NUMERIC(12,2) DEFAULT 0,
                valor_inventario NUMERIC(12,2) DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ventas (
                id INTEGER PRIMARY KEY,
                usuario TEXT,
                codigo TEXT,
                nombre TEXT,
                cantidad INTEGER DEFAULT 0,
                subtotal NUMERIC(12,2) DEFAULT 0,
                metodo TEXT,
                fecha TIMESTAMP
            )
        """))

        total_inv = conn.execute(text("SELECT COUNT(*) FROM inventario")).scalar()
        total_ventas = conn.execute(text("SELECT COUNT(*) FROM ventas")).scalar()

        # Solo migra desde Excel si las tablas están vacías. No borra datos ya guardados.
        if total_inv == 0 and os.path.exists(INVENTARIO_FILE):
            try:
                df_inv = normalizar_inventario(pd.read_excel(INVENTARIO_FILE))
                if not df_inv.empty:
                    df_inv.to_sql("inventario", conn, if_exists="append", index=False)
                    print("Inventario migrado desde Excel a PostgreSQL")
            except Exception as e:
                print("No se pudo migrar inventario.xlsx:", e)

        if total_ventas == 0 and os.path.exists(VENTAS_FILE):
            try:
                df_ven = normalizar_ventas(pd.read_excel(VENTAS_FILE))
                if not df_ven.empty:
                    df_ven.to_sql("ventas", conn, if_exists="append", index=False)
                    print("Ventas migradas desde Excel a PostgreSQL")
            except Exception as e:
                print("No se pudo migrar ventas.xlsx:", e)


def cargar_inventario():
    try:
        with engine.connect() as conn:
            df = pd.read_sql("SELECT * FROM inventario ORDER BY codigo", conn)
        return normalizar_inventario(df)
    except Exception as e:
        print("ERROR LEYENDO INVENTARIO EN BD:", e)
        return pd.DataFrame(columns=COLUMNAS_INVENTARIO)


def guardar_inventario(df):
    df = normalizar_inventario(df)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM inventario"))
        if not df.empty:
            df.to_sql("inventario", conn, if_exists="append", index=False)


def cargar_ventas():
    try:
        with engine.connect() as conn:
            df = pd.read_sql("SELECT * FROM ventas ORDER BY id", conn)
        return normalizar_ventas(df)
    except Exception as e:
        print("ERROR LEYENDO VENTAS EN BD:", e)
        return pd.DataFrame(columns=COLUMNAS_VENTAS)


def guardar_ventas(df):
    df = normalizar_ventas(df)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM ventas"))
        if not df.empty:
            df.to_sql("ventas", conn, if_exists="append", index=False)


def cargar_excel():
    return cargar_inventario()


def buscar_producto(busqueda):
    df = cargar_inventario()
    busqueda = limpiar(busqueda)
    if df.empty or not busqueda:
        return None

    filtro = (df["codigo"].astype(str).str.upper() == busqueda) | (df["nombre"].astype(str).str.upper() == busqueda)
    resultado = df[filtro]
    if resultado.empty:
        return None

    p = resultado.iloc[0]
    return {
        "codigo": p["codigo"],
        "nombre": p["nombre"],
        "stock": int(p["stock"] or 0),
        "costo_unitario": float(p["costo_unitario"] or 0)
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

    filtro_editorial = request.args.get("editorial", "").strip()
    filtro_categoria = request.args.get("categoria", "").strip()

    editoriales = sorted(df["editorial"].dropna().astype(str).unique()) if not df.empty else []
    categorias = sorted(df["categoria"].dropna().astype(str).unique()) if not df.empty else []

    if filtro_editorial:
        df = df[df["editorial"].astype(str).str.strip() == filtro_editorial]

    if filtro_categoria:
        df = df[df["categoria"].astype(str).str.strip() == filtro_categoria]

    sugerencias = []
    tabla = ""

    if not df.empty:
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
        tabla=tabla,
        filtro_editorial=filtro_editorial,
        filtro_categoria=filtro_categoria
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
        editoriales = sorted(df["editorial"].dropna().astype(str).unique())
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
    return send_file(archivo, as_attachment=True, download_name="inventario.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/inventario/agregar", methods=["POST"])
def agregar_producto():
    if login_requerido():
        return redirect("/login")
    if not es_admin():
        return redirect("/")

    codigo = limpiar(request.form.get("codigo"))
    nombre = request.form.get("nombre", "").strip()
    editorial = request.form.get("editorial", "").strip()
    categoria = request.form.get("categoria", "").strip()
    stock = numero(request.form.get("stock"), int)
    precio = numero(request.form.get("precio"), float)

    if not codigo or not nombre:
        return redirect("/inventario")

    with db_lock:
        df = cargar_inventario()
        fila = {
            "codigo": codigo,
            "nombre": nombre,
            "editorial": editorial,
            "categoria": categoria,
            "compras": stock,
            "ventas": 0,
            "stock": stock,
            "costo_unitario": precio,
            "precio_venta": precio,
            "utilidad_prod": 0,
            "valor_inventario": stock * precio
        }

        if codigo in df["codigo"].astype(str).str.upper().values:
            idx = df.index[df["codigo"].astype(str).str.upper() == codigo][0]
            for k, v in fila.items():
                df.loc[idx, k] = v
        else:
            df = pd.concat([df, pd.DataFrame([fila])], ignore_index=True)

        guardar_inventario(df)

    return redirect("/inventario")


@app.route("/inventario/actualizar", methods=["POST"])
def actualizar_producto():
    if login_requerido():
        return redirect("/login")
    if not es_admin():
        return redirect("/")

    codigo = limpiar(request.form.get("codigo"))
    nuevo_nombre = request.form.get("nombre", "").strip()
    nuevo_stock = request.form.get("stock")
    nuevo_precio = request.form.get("precio")

    if not codigo:
        return redirect("/inventario")

    with db_lock:
        df = cargar_inventario()
        filtro = df["codigo"].astype(str).str.upper() == codigo
        if filtro.any():
            idx = df.index[filtro][0]
            if nuevo_nombre != "":
                df.loc[idx, "nombre"] = nuevo_nombre
            if nuevo_stock not in [None, ""]:
                df.loc[idx, "stock"] = numero(nuevo_stock, int)
            if nuevo_precio not in [None, ""]:
                precio_final = numero(nuevo_precio, float)
                df.loc[idx, "costo_unitario"] = precio_final
                df.loc[idx, "precio_venta"] = precio_final
            df.loc[idx, "valor_inventario"] = int(df.loc[idx, "stock"]) * float(df.loc[idx, "costo_unitario"])
            guardar_inventario(df)

    return redirect("/inventario")


@app.route("/inventario/eliminar", methods=["POST"])
def eliminar_producto():
    if login_requerido():
        return redirect("/login")
    if not es_admin():
        return redirect("/")

    codigo = limpiar(request.form.get("codigo"))
    if not codigo:
        return redirect("/inventario")

    with db_lock:
        df = cargar_inventario()
        df = df[df["codigo"].astype(str).str.upper() != codigo]
        guardar_inventario(df)

    return redirect("/inventario")


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

    fecha_manual = request.form.get("fecha_venta")
    if fecha_manual and fecha_manual.strip() != "":
        try:
            fecha_venta = datetime.strptime(fecha_manual, "%Y-%m-%dT%H:%M")
        except Exception:
            fecha_venta = hora_peru()
    else:
        fecha_venta = hora_peru()

    with db_lock:
        df_inv = cargar_inventario()
        df_ventas = cargar_ventas()

        # Validar stock antes de guardar cualquier cosa
        for item in carrito:
            codigo = limpiar(item["codigo"])
            cantidad = int(item["cantidad"])
            filtro = df_inv["codigo"].astype(str).str.upper() == codigo
            if not filtro.any():
                return redirect("/")
            idx = df_inv.index[filtro][0]
            if cantidad > int(df_inv.loc[idx, "stock"]):
                return redirect("/")

        siguiente_id = int(df_ventas["id"].max()) + 1 if not df_ventas.empty and df_ventas["id"].max() > 0 else 1
        nuevas_ventas = []

        for item in carrito:
            codigo = limpiar(item["codigo"])
            cantidad = int(item["cantidad"])
            filtro = df_inv["codigo"].astype(str).str.upper() == codigo
            idx = df_inv.index[filtro][0]

            df_inv.loc[idx, "stock"] = int(df_inv.loc[idx, "stock"]) - cantidad
            df_inv.loc[idx, "ventas"] = int(df_inv.loc[idx, "ventas"]) + cantidad
            df_inv.loc[idx, "valor_inventario"] = int(df_inv.loc[idx, "stock"]) * float(df_inv.loc[idx, "costo_unitario"])

            nuevas_ventas.append({
                "id": siguiente_id,
                "usuario": session["user"],
                "codigo": codigo,
                "nombre": item["nombre"],
                "cantidad": cantidad,
                "subtotal": float(item["subtotal"]),
                "metodo": metodo.upper(),
                "fecha": fecha_venta
            })
            siguiente_id += 1

        df_ventas = pd.concat([df_ventas, pd.DataFrame(nuevas_ventas)], ignore_index=True)
        guardar_inventario(df_inv)
        guardar_ventas(df_ventas)

    session["carrito"] = []
    return redirect("/")


def obtener_ventas_filtradas():
    df = cargar_ventas()
    if df.empty:
        return df

    inicio = request.args.get("inicio")
    fin = request.args.get("fin")
    usuario = request.args.get("usuario")
    metodo = request.args.get("metodo")

    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")

    if inicio:
        df = df[df["fecha"] >= pd.to_datetime(inicio, errors="coerce")]

    if fin:
        try:
            fin_dt = datetime.strptime(fin, "%Y-%m-%d") + timedelta(days=1)
            df = df[df["fecha"] < fin_dt]
        except Exception:
            pass

    if usuario:
        df = df[df["usuario"].astype(str).str.upper() == usuario.upper()]

    if metodo:
        df = df[df["metodo"].astype(str).str.upper() == metodo.upper()]

    return df.sort_values("fecha", ascending=False)


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
    except Exception:
        producto_top = "Sin datos"

    try:
        vendedor_top = df.groupby("usuario")["subtotal"].sum().sort_values(ascending=False).index[0]
    except Exception:
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
    return send_file(archivo, as_attachment=True, download_name="ventas.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/ventas/eliminar/<int:id>")
def eliminar_venta(id):
    if login_requerido():
        return redirect("/login")
    if not es_admin():
        return redirect("/ventas")

    with db_lock:
        df_ventas = cargar_ventas()
        df_inv = cargar_inventario()

        venta = df_ventas[df_ventas["id"] == id]
        if not venta.empty:
            row = venta.iloc[0]
            codigo = limpiar(row["codigo"])
            cantidad = int(row["cantidad"])

            filtro = df_inv["codigo"].astype(str).str.upper() == codigo
            if filtro.any():
                idx = df_inv.index[filtro][0]
                df_inv.loc[idx, "stock"] = int(df_inv.loc[idx, "stock"]) + cantidad
                df_inv.loc[idx, "ventas"] = max(0, int(df_inv.loc[idx, "ventas"]) - cantidad)
                df_inv.loc[idx, "valor_inventario"] = int(df_inv.loc[idx, "stock"]) * float(df_inv.loc[idx, "costo_unitario"])

            df_ventas = df_ventas[df_ventas["id"] != id]
            guardar_inventario(df_inv)
            guardar_ventas(df_ventas)

    return redirect("/ventas")


@app.route("/reemplazar_inventario", methods=["POST"])
def reemplazar_inventario():
    if login_requerido():
        return redirect("/login")
    if not es_admin():
        return redirect("/")

    if "archivo" not in request.files:
        return "No se subió ningún archivo"

    archivo = request.files["archivo"]
    if archivo.filename == "":
        return "No seleccionaste ningún archivo"
    if not archivo.filename.endswith(".xlsx"):
        return "Solo se permite archivo .xlsx"

    try:
        df = pd.read_excel(archivo)
        df = normalizar_inventario(df)
        with db_lock:
            guardar_inventario(df)
        return redirect("/inventario")
    except Exception as e:
        return f"Error al reemplazar inventario: {e}"


inicializar_bd()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
