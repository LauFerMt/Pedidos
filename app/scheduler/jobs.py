# app/scheduler/jobs.py
from datetime import datetime, date, timedelta
from flask import current_app
from ..database import get_db
from ..telegram.send_message import send_telegram_message

def _fmt_fecha(d: date) -> str:
    # Formato amigable en español (simple)
    meses = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"]
    return f"{d.day} de {meses[d.month-1]} {d.year}"

def job_entregas_hoy():
    app = current_app
    db = get_db(app)
    hoy = date.today()

    rows = db.execute("""
        SELECT codigo, cliente_nombre, modelo, colonia, municipio, telefono_1
          FROM pedidos
         WHERE fecha_entrega = date(?)
           AND estado IN ('pendiente','con_anticipo','en_produccion','programado_entrega')
         ORDER BY id ASC
    """, (hoy.isoformat(),)).fetchall()

    if not rows:
        # Silencioso: no enviamos nada si no hay entregas hoy
        return

    lines = [f"📦 ENTREGAS HOY — {_fmt_fecha(hoy)}"]
    for r in rows:
        tel = r["telefono_1"] or "-"
        lines.append(f"• #{r['codigo']} — {r['cliente_nombre']} — {r['modelo']} — {r['colonia']}/{r['municipio']} — Tel: {tel}")

    lines.append(f"\nTotal: {len(rows)} pedido(s)")
    send_telegram_message("\n".join(lines))

def job_produccion_hoy():
    app = current_app
    db = get_db(app)
    hoy = date.today()

    # Producción hoy => entregas en N días (N = dias_pre_produccion; por default 1)
    rows = db.execute("""
        SELECT codigo, vendedor, modelo, total, notas, dias_pre_produccion, fecha_entrega
          FROM pedidos
         WHERE requiere_produccion = 1
           AND fecha_entrega IS NOT NULL
           AND date(fecha_entrega, '-' || dias_pre_produccion || ' day') = date(?)
           AND estado IN ('pendiente','con_anticipo','en_produccion','programado_entrega')
         ORDER BY id ASC
    """, (hoy.isoformat(),)).fetchall()

    if not rows:
        return

    # Tomamos la fecha de entrega objetivo (la de mañana o N días después) del primer registro para encabezar
    # Pueden ser varias fechas mezcladas si hay diferentes N; mostramos una línea por pedido.
    lines = [f"⚙️ PRODUCCIÓN HOY — para entregar próximamente"]
    for r in rows:
        f_entrega = r["fecha_entrega"] or ""
        lines.append(
            f"• #{r['codigo']} — {r['modelo']} — Vendedora: {r['vendedor']} — Total: ${r['total']:.2f}\n  Entrega: {f_entrega} · Notas: {r['notas'] or '—'}"
        )

    lines.append(f"\nTotal: {len(rows)} pedido(s)")
    send_telegram_message("\n".join(lines))

def run_all_now():
    """Gatillo manual para probar ambos envíos sin esperar a las 07:00."""
    job_entregas_hoy()
    job_produccion_hoy()