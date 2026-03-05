# app/routes/admin.py
import os
from flask import Blueprint, current_app, render_template, request, redirect, url_for, session, abort, send_file, flash
from io import BytesIO
from datetime import datetime, date

from ..database import get_db
from ..telegram.send_message import send_telegram_message
from ..utils.auth import login_admin, require_admin

bp = Blueprint("admin", __name__, url_prefix="/admin")

# ---------- LOGIN / LOGOUT ----------
@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("admin/login.html")
    user = (request.form.get("user") or "").strip()
    pwd = (request.form.get("password") or "").strip()
    if login_admin(user, pwd):
        session["admin_ok"] = True
        next_url = request.args.get("next") or url_for("admin.list_pedidos")
        return redirect(next_url)
    return render_template("admin/login.html", error="Credenciales inválidas"), 401

@bp.get("/logout")
@require_admin
def logout():
    session.clear()
    return redirect(url_for("admin.login"))

# ---------- LISTADO DE PEDIDOS ----------
@bp.route("/pedidos", methods=["GET"])
@require_admin
def list_pedidos():
    db = get_db(current_app)

    estado = request.args.get("estado", "").strip()
    vendedor = request.args.get("vendedor", "").strip()
    fdel = request.args.get("del", "").strip()
    fal = request.args.get("al", "").strip()
    entrega_hoy = request.args.get("entrega_hoy", "").strip()

    sql = """
        SELECT id, codigo, vendedor, cliente_nombre, municipio, colonia, total,
               fecha_entrega, estado, created_at
          FROM pedidos
         WHERE 1=1
    """
    params = []
    if estado:
        sql += " AND estado = ?"
        params.append(estado)
    if vendedor:
        sql += " AND vendedor LIKE ?"
        params.append(f"%{vendedor}%")
    if fdel:
        sql += " AND date(created_at) >= date(?)"
        params.append(fdel)
    if fal:
        sql += " AND date(created_at) <= date(?)"
        params.append(fal)
    if entrega_hoy == "1":
        hoy = date.today().isoformat()
        sql += " AND date(fecha_entrega) = date(?)"
        params.append(hoy)

    sql += " ORDER BY id DESC LIMIT 200"
    pedidos = db.execute(sql, params).fetchall()

    return render_template(
        "admin/pedidos_list.html",
        pedidos=pedidos,
        filtros={"estado": estado, "vendedor": vendedor, "del": fdel, "al": fal, "entrega_hoy": entrega_hoy},
    )

# ---------- DETALLE / EDICIÓN ----------
@bp.route("/pedidos/<int:pedido_id>", methods=["GET", "POST"])
@require_admin
def pedido_detalle(pedido_id: int):
    db = get_db(current_app)

    if request.method == "GET":
        p = db.execute("SELECT * FROM pedidos WHERE id=?", (pedido_id,)).fetchone()
        if not p:
            abort(404)
        condiciones = db.execute(
            "SELECT * FROM condiciones_catalogo WHERE activo=1 ORDER BY orden ASC, id ASC"
        ).fetchall()
        marcadas = db.execute(
            "SELECT condicion_id FROM pedido_condicion WHERE pedido_id=?", (pedido_id,)
        ).fetchall()
        marcadas_ids = {r["condicion_id"] for r in marcadas}
        adj = db.execute(
            "SELECT id, filename, mime_type, uploaded_at FROM adjuntos WHERE pedido_id=? AND tipo='anticipo'",
            (pedido_id,),
        ).fetchall()
        return render_template(
            "admin/pedido_detalle.html",
            p=p,
            condiciones=condiciones,
            marcadas_ids=marcadas_ids,
            adjuntos=adj,
        )

    # POST: actualizar
    estado = (request.form.get("estado") or "").strip()
    fecha_entrega = (request.form.get("fecha_entrega") or "").strip()
    requiere_prod = 1 if request.form.get("requiere_produccion") == "1" else 0

    # >>> Asegurar el mismo nombre que el input del template
    try:
        dias_pre_produccion = int(request.form.get("dias_pre_produccion") or 1)
    except ValueError:
        dias_pre_produccion = 1

    notas = (request.form.get("notas") or "").strip()

    # Validación de fecha (si viene)
    if fecha_entrega:
        try:
            _ = datetime.strptime(fecha_entrega, "%Y-%m-%d")
        except ValueError:
            flash("Fecha de entrega inválida. Usa formato YYYY-MM-DD.", "err")
            return redirect(url_for("admin.pedido_detalle", pedido_id=pedido_id))

    db.execute(
        """
        UPDATE pedidos
           SET estado=?,
               fecha_entrega=?,
               requiere_produccion=?,
               dias_pre_produccion=?,
               notas=?
         WHERE id=?
        """,
        (
            estado or "pendiente",
            fecha_entrega if fecha_entrega else None,
            requiere_prod,
            dias_pre_produccion,
            notas,
            pedido_id,
        ),
    )
    db.commit()

    # Actualizar condiciones (si llegaron)
    seleccionados = request.form.getlist("condicion_id")
    if seleccionados is not None:
        db.execute("DELETE FROM pedido_condicion WHERE pedido_id=?", (pedido_id,))
        if seleccionados:
            db.executemany(
                "INSERT INTO pedido_condicion (pedido_id, condicion_id) VALUES (?,?)",
                [(pedido_id, int(cid)) for cid in seleccionados if str(cid).isdigit()],
            )
        # reconstruir texto congelado
        ids_validos = [int(cid) for cid in seleccionados if str(cid).isdigit()]
        instrucciones_texto = ""
        if ids_validos:
            qmarks = ",".join(["?"] * len(ids_validos))
            rs = db.execute(
                f"SELECT titulo FROM condiciones_catalogo WHERE id IN ({qmarks})", ids_validos
            ).fetchall()
            instrucciones_texto = "\n".join([f"- {r['titulo']}" for r in rs])
        db.execute(
            "UPDATE pedidos SET instrucciones_entrega_texto=? WHERE id=?",
            (instrucciones_texto, pedido_id),
        )
        db.commit()

    flash("Pedido actualizado.", "ok")
    return redirect(url_for("admin.pedido_detalle", pedido_id=pedido_id))

# ---------- VER ADJUNTO ----------
@bp.get("/adjunto/<int:adjunto_id>")
@require_admin
def ver_adjunto(adjunto_id: int):
    db = get_db(current_app)
    r = db.execute(
        "SELECT filename, mime_type, data FROM adjuntos WHERE id=?", (adjunto_id,)
    ).fetchone()
    if not r:
        abort(404)
    return send_file(
        BytesIO(r["data"]),
        mimetype=r["mime_type"],
        download_name=r["filename"],
    )

# ---------- CRUD CONDICIONES ----------
@bp.route("/condiciones", methods=["GET", "POST"])
@require_admin
def condiciones_list():
    db = get_db(current_app)
    if request.method == "POST":
        cid = (request.form.get("id") or "").strip()
        titulo = (request.form.get("titulo") or "").strip()
        activo = 1 if request.form.get("activo") == "1" else 0
        try:
            orden = int(request.form.get("orden") or 0)
        except ValueError:
            orden = 0
        if not titulo:
            flash("El título no puede estar vacío.", "err")
            return redirect(url_for("admin.condiciones_list"))
        if cid:
            db.execute(
                "UPDATE condiciones_catalogo SET titulo=?, activo=?, orden=? WHERE id=?",
                (titulo, activo, orden, int(cid)), 
            )
        else:
            db.execute(
                "INSERT INTO condiciones_catalogo (titulo, activo, orden) VALUES (?,?,?)",
                (titulo, activo, orden),
            )
        db.commit()
        return redirect(url_for("admin.condiciones_list"))

    rows = db.execute(
        "SELECT * FROM condiciones_catalogo ORDER BY orden ASC, id ASC"
    ).fetchall()
    return render_template("admin/condiciones.html", condiciones=rows)

@bp.get("/")
def home_redirect():
    if session.get("admin_ok"):
        return redirect(url_for("admin.list_pedidos"))
    return redirect(url_for("admin.login"))

# ---------- PING TELEGRAM ----------
@bp.get("/ping-telegram")
@require_admin
def ping_telegram():
    ok = send_telegram_message(
        "✅ Prueba: el sistema de pedidos ya puede enviar mensajes (desde admin)."
    )
    return {"sent": ok}, 200 if ok else 500
