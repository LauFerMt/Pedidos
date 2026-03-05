# app/routes/pedidos.py
import os
from flask import Blueprint, request, render_template, redirect, url_for, current_app
from ..database import get_db
from ..telegram.send_message import send_telegram_message
from ..utils.validators import normalize_phone, is_valid_cp, is_valid_url

bp = Blueprint("pedidos", __name__)

ALLOWED_EXT = {"jpg", "jpeg", "png", "pdf"}

def allowed_file(filename: str) -> bool:
    """Valida extensión permitida para comprobantes."""
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXT

@bp.route("/pedido", methods=["GET", "POST"])
def pedido_form():
    """
    GET  -> renderiza el formulario público.
    POST -> valida, guarda en BD, genera código, notifica Telegram y redirige a /gracias.
    """
    db = get_db(current_app)

    # Traer catálogo de condiciones (activas) para mostrar como checkboxes
    condiciones = db.execute(
        "SELECT id, titulo FROM condiciones_catalogo WHERE activo=1 ORDER BY orden ASC, id ASC"
    ).fetchall()

    if request.method == "GET":
        vendedor_prefill = request.args.get("vendedor", "").strip()
        return render_template(
            "pedido_form.html",
            condiciones=condiciones,
            vendedor_prefill=vendedor_prefill,
            max_mb=int(os.getenv("MAX_UPLOAD_MB", "10")),
        )

    # -------------------- POST: Validaciones y guardado --------------------
    form = request.form
    files = request.files

    # Vendedor
    vendedor = (form.get("vendedor") or "").strip()

    # Cliente
    cliente_nombre = (form.get("cliente_nombre") or "").strip()
    telefono_1 = normalize_phone(form.get("telefono_1") or "")
    telefono_2 = normalize_phone(form.get("telefono_2") or "")
    referencia = (form.get("referencia") or "").strip()
    municipio = (form.get("municipio") or "").strip()
    colonia = (form.get("colonia") or "").strip()
    calle = (form.get("calle") or "").strip()
    numero = (form.get("numero") or "").strip()
    manzana = (form.get("manzana") or "").strip()
    lote = (form.get("lote") or "").strip()
    cp = (form.get("cp") or "").strip()
    ubicacion_url = (form.get("ubicacion_url") or "").strip()

    # Producto
    modelo = (form.get("modelo") or "").strip()
    color = (form.get("color") or "").strip()
    tarja_posicion = (form.get("tarja_posicion") or "").strip()
    parrilla_posicion = (form.get("parrilla_posicion") or "").strip()

    # Costos base
    try:
        precio = float(form.get("precio") or 0)
        envio_costo = float(form.get("envio_costo") or 0)
    except ValueError:
        return render_template(
            "pedido_form.html",
            condiciones=condiciones,
            error="Precio/Envío inválidos.",
            max_mb=int(os.getenv("MAX_UPLOAD_MB", "10")),
        ), 400

    # Instalación
    instalacion_aplica = 1 if form.get("instalacion_aplica") == "1" else 0
    try:
        instalacion_costo = float(form.get("instalacion_costo") or 0)
    except ValueError:
        return render_template(
            "pedido_form.html",
            condiciones=condiciones,
            error="Costo de instalación inválido.",
            max_mb=int(os.getenv("MAX_UPLOAD_MB", "10")),
        ), 400
    if instalacion_aplica and instalacion_costo < 0:
        return render_template(
            "pedido_form.html",
            condiciones=condiciones,
            error="El costo de instalación debe ser ≥ 0.",
            max_mb=int(os.getenv("MAX_UPLOAD_MB", "10")),
        ), 400

    # Total del lado servidor (evitamos manipulación del DOM)
    total = round(precio + envio_costo + (instalacion_costo if instalacion_aplica else 0), 2)

    # Anticipo
    con_anticipo = 1 if form.get("con_anticipo") == "1" else 0
    anticipo = 0.0
    if con_anticipo:
        try:
            anticipo = float(form.get("anticipo") or 0)
        except ValueError:
            return render_template(
                "pedido_form.html",
                condiciones=condiciones,
                error="Monto de anticipo inválido.",
                max_mb=int(os.getenv("MAX_UPLOAD_MB", "10")),
            ), 400
        if anticipo < 0 or anticipo > total:
            return render_template(
                "pedido_form.html",
                condiciones=condiciones,
                error="El anticipo debe ser ≥ 0 y ≤ total.",
                max_mb=int(os.getenv("MAX_UPLOAD_MB", "10")),
            ), 400
    saldo_pendiente = round(total - anticipo, 2)

    # Validaciones mínimas obligatorias
    if not (vendedor and cliente_nombre and telefono_1 and municipio and colonia and calle and numero and cp and modelo and color and tarja_posicion and parrilla_posicion):
        return render_template(
            "pedido_form.html",
            condiciones=condiciones,
            error="Faltan campos obligatorios. Revisa los requeridos.",
            max_mb=int(os.getenv("MAX_UPLOAD_MB", "10")),
        ), 400
    if not is_valid_cp(cp):
        return render_template(
            "pedido_form.html",
            condiciones=condiciones,
            error="El CP debe ser de 5 dígitos.",
            max_mb=int(os.getenv("MAX_UPLOAD_MB", "10")),
        ), 400
    if ubicacion_url and not is_valid_url(ubicacion_url):
        return render_template(
            "pedido_form.html",
            condiciones=condiciones,
            error="El link de ubicación no es válido.",
            max_mb=int(os.getenv("MAX_UPLOAD_MB", "10")),
        ), 400

    # Insertar pedido (con codigo NULL temporal, se actualiza después con An-(id))
    cur = db.cursor()
    cur.execute("""
        INSERT INTO pedidos (
            codigo, vendedor, cliente_nombre, telefono_1, telefono_2, referencia,
            municipio, colonia, calle, numero, manzana, lote, cp, ubicacion_url,
            modelo, color, tarja_posicion, parrilla_posicion,
            precio, envio_costo, total, con_anticipo, anticipo, saldo_pendiente,
            requiere_produccion, dias_pre_produccion, estado, instrucciones_entrega_texto, notas,
            instalacion_aplica, instalacion_costo
        ) VALUES (
            NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            1, 1, 'pendiente', '', ?, ?, ?
        )
    """, (
        vendedor, cliente_nombre, telefono_1, telefono_2, referencia,
        municipio, colonia, calle, numero, manzana, lote, cp, ubicacion_url,
        modelo, color, tarja_posicion, parrilla_posicion,
        precio, envio_costo, total, con_anticipo, anticipo, saldo_pendiente,
        (form.get("notas") or ""),
        instalacion_aplica, instalacion_costo
    ))
    db.commit()
    pedido_id = cur.lastrowid

    # Generar código An-(id) y actualizar
    codigo = f"An-{pedido_id}"
    cur.execute("UPDATE pedidos SET codigo=? WHERE id=?", (codigo, pedido_id))
    db.commit()

    # Guardar condiciones seleccionadas y construir texto congelado
    seleccionados = request.form.getlist("condicion_id")
    instrucciones_texto = ""
    if seleccionados:
        # Insertar relación en tabla puente
        cur.executemany(
            "INSERT OR IGNORE INTO pedido_condicion (pedido_id, condicion_id) VALUES (?,?)",
            [(pedido_id, int(cid)) for cid in seleccionados if str(cid).isdigit()]
        )
        # Armar el texto con los títulos
        ids_validos = [int(cid) for cid in seleccionados if str(cid).isdigit()]
        if ids_validos:
            qmarks = ",".join(["?"] * len(ids_validos))
            rs = db.execute(
                f"SELECT titulo FROM condiciones_catalogo WHERE id IN ({qmarks})",
                ids_validos
            ).fetchall()
            instrucciones_texto = "\n".join([f"- {r['titulo']}" for r in rs])
            cur.execute(
                "UPDATE pedidos SET instrucciones_entrega_texto=? WHERE id=?",
                (instrucciones_texto, pedido_id)
            )
            db.commit()

    # Subir comprobante del anticipo (como BLOB)
    if con_anticipo and "comprobante" in files:
        f = files["comprobante"]
        if f and f.filename:
            if not allowed_file(f.filename):
                return render_template(
                    "pedido_form.html",
                    condiciones=condiciones,
                    error="Formato de archivo no permitido (usa jpg, jpeg, png o pdf).",
                    max_mb=int(os.getenv("MAX_UPLOAD_MB", "10")),
                ), 400
            data = f.read()
            cur.execute(
                "INSERT INTO adjuntos (pedido_id, tipo, filename, mime_type, data) VALUES (?,?,?,?,?)",
                (pedido_id, "anticipo", f.filename, f.mimetype, data)
            )
            db.commit()

    # Construir mensaje para Telegram
    lines = [
        f"🆕 Pedido #{codigo}",
        "",
        f"👤 Vendedor: {vendedor}",
        f"🧩 Modelo: {modelo}",
        f"🎨 Color: {color} | Tarja: {tarja_posicion} | Parrilla: {parrilla_posicion}",
        "",
        f"💰 Precio: ${precio:.2f} | Envío: ${envio_costo:.2f} | Total: ${total:.2f}",
    ]
    if instalacion_aplica:
        lines.append(f"🛠️ Instalación: ${instalacion_costo:.2f}")
    if con_anticipo:
        lines.append(f"💳 Anticipo: ${anticipo:.2f} | Saldo: ${saldo_pendiente:.2f} (Con comprobante)")
    lines += [
        "",
        f"📍 Cliente: {cliente_nombre}",
        f"📞 Tel: {telefono_1}" + (f" / {telefono_2}" if telefono_2 else ""),
        f"🏠 {calle} {numero}, {colonia}, {municipio}, CP {cp}",
        f"🗺️ {ubicacion_url or 'Sin link'}",
        "",
        f"📝 Ref: {referencia or '—'}",
    ]
    if instrucciones_texto:
        lines += ["📦 Condiciones:", instrucciones_texto]

    # Enviar (sin romper el flujo si falla)
    try:
        send_telegram_message("\n".join(lines))
    except Exception as e:
        current_app.logger.error("Error enviando Telegram: %s", e)

    # Redirigir a pantalla de agradecimiento
    return redirect(url_for("pedidos.pedido_gracias", codigo=codigo))

@bp.get("/gracias")
def pedido_gracias():
    """Pantalla simple con código de pedido."""
    codigo = request.args.get("codigo", "")
    return render_template("pedido_gracias.html", codigo=codigo)