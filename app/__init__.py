# app/__init__.py (fragmento relevante)
from flask import Flask
from dotenv import load_dotenv
import os
from datetime import datetime
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

def create_app():
    load_dotenv()

    app = Flask(__name__, instance_relative_config=True)
    app.secret_key = os.getenv("SECRET_KEY", "dev-secret")
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "10")) * 1024 * 1024

    os.makedirs(app.instance_path, exist_ok=True)
    app.config["DATABASE_PATH"] = os.path.join(app.instance_path, "database.db")

    app.config["TIMEZONE"] = os.getenv("TZ", "America/Mexico_City")
    app.tz = pytz.timezone(app.config["TIMEZONE"])

    # DB
    from .database import init_db
    init_db(app)

    # Blueprints
    from .routes.pedidos import bp as pedidos_bp
    app.register_blueprint(pedidos_bp)

    from .routes.admin import bp as admin_bp
    app.register_blueprint(admin_bp)

    # Health
    @app.get("/health")
    def health():
        now_local = datetime.now(app.tz).strftime("%Y-%m-%d %H:%M:%S")
        return {"status": "ok", "time": now_local}

    # ---------- Scheduler ----------
    scheduler = BackgroundScheduler(timezone=app.tz)

    from .scheduler.jobs import job_entregas_hoy, job_produccion_hoy, run_all_now

    # Todos los días a las 07:00 hora local (CDMX)
    trigger_7am = CronTrigger(hour=7, minute=0, timezone=app.tz)

    scheduler.add_job(job_entregas_hoy, trigger_7am, id="entregas_hoy", replace_existing=True)
    scheduler.add_job(job_produccion_hoy, trigger_7am, id="produccion_hoy", replace_existing=True)

    scheduler.start()

    # Gatillo manual de pruebas (para no esperar 07:00)
    @app.get("/admin/scheduler/run-now")
    def scheduler_run_now():
        run_all_now()
        return {"ok": True, "message": "Jobs ejecutados manualmente"}

    return app