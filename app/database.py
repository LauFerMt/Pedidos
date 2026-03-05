# app/database.py
import sqlite3
from flask import g
from contextlib import closing

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pedidos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT,
    vendedor TEXT,
    cliente_nombre TEXT,
    telefono_1 TEXT,
    telefono_2 TEXT,
    referencia TEXT,
    municipio TEXT,
    colonia TEXT,
    calle TEXT,
    numero TEXT,
    manzana TEXT,
    lote TEXT,
    cp TEXT,
    ubicacion_url TEXT,
    modelo TEXT,
    color TEXT,
    tarja_posicion TEXT,
    parrilla_posicion TEXT,
    precio REAL,
    envio_costo REAL,
    total REAL,
    con_anticipo INTEGER DEFAULT 0,
    anticipo REAL,
    saldo_pendiente REAL,
    fecha_entrega DATE,
    requiere_produccion INTEGER DEFAULT 1,
    dias_pre_produccion INTEGER DEFAULT 1,
    estado TEXT DEFAULT 'pendiente',
    instrucciones_entrega_texto TEXT,
    notas TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS condiciones_catalogo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    activo INTEGER DEFAULT 1,
    orden INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pedido_condicion (
    pedido_id INTEGER NOT NULL,
    condicion_id INTEGER NOT NULL,
    PRIMARY KEY (pedido_id, condicion_id),
    FOREIGN KEY (pedido_id) REFERENCES pedidos(id) ON DELETE CASCADE,
    FOREIGN KEY (condicion_id) REFERENCES condiciones_catalogo(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS adjuntos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    filename TEXT,
    mime_type TEXT,
    data BLOB,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (pedido_id) REFERENCES pedidos(id) ON DELETE CASCADE
);
"""

SEED_CONDICIONES = [
    ("SE ENTREGA A PIE DE DOMICILIO", 1, 1),
    ("NO SE REALIZA MANIOBRA", 1, 2),
    ("NO HAY HORARIO DE ENTREGA", 1, 3),
]

def get_db(app):
    """Obtiene/crea la conexión SQLite y setea row_factory."""
    if "db" not in g:
        g.db = sqlite3.connect(
            app.config["DATABASE_PATH"],
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False
        )
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db(app):
    """Crea tablas si no existen, aplica seeds y migraciones simples."""
    @app.teardown_appcontext
    def teardown_db(exception):
        close_db()

    with app.app_context():
        db = get_db(app)
        with closing(db.cursor()) as cur:
            # 1) Crear esquema base
            cur.executescript(SCHEMA_SQL)

            # 2) Semilla del catálogo (si está vacío)
            cur.execute("SELECT COUNT(*) AS c FROM condiciones_catalogo")
            if cur.fetchone()["c"] == 0:
                cur.executemany(
                    "INSERT INTO condiciones_catalogo (titulo, activo, orden) VALUES (?,?,?)",
                    SEED_CONDICIONES
                )

            # 3) --- MIGRACIONES SIMPLES ---
            #    a) Campos de instalación (nuevos)
            cur.execute("PRAGMA table_info(pedidos)")
            cols = [r["name"] for r in cur.fetchall()]

            if "instalacion_aplica" not in cols:
                cur.execute("ALTER TABLE pedidos ADD COLUMN instalacion_aplica INTEGER DEFAULT 0")
            if "instalacion_costo" not in cols:
                cur.execute("ALTER TABLE pedidos ADD COLUMN instalacion_costo REAL DEFAULT 0")

            db.commit()