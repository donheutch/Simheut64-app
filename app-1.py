"""
SimHeut96 — Backend de l'appli d'activation de licences
=========================================================
Lance avec :  uvicorn app:app --host 0.0.0.0 --port 8000

Variables d'environnement requises :
  SIMHEUT96_SECRET_KEY       -> clé secrète longue et aléatoire
  SIMHEUT96_ADMIN_PASSWORD   -> mot de passe pour la page admin

Variables optionnelles (envoi d'email des codes) :
  SIMHEUT96_SMTP_HOST, SIMHEUT96_SMTP_PORT, SIMHEUT96_SMTP_USER,
  SIMHEUT96_SMTP_PASSWORD, SIMHEUT96_SMTP_FROM
  Si absentes, la génération de code fonctionne normalement mais
  aucun email n'est envoyé (l'admin récupère le code à la main).
"""

import os
import sqlite3
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

import license as lic

APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "data" / "license.db"
DB_PATH.parent.mkdir(exist_ok=True)

ADMIN_PASSWORD = os.environ.get("SIMHEUT96_ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    raise RuntimeError("La variable d'environnement SIMHEUT96_ADMIN_PASSWORD doit être définie.")

SMTP_HOST = os.environ.get("SIMHEUT96_SMTP_HOST")
SMTP_PORT = int(os.environ.get("SIMHEUT96_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SIMHEUT96_SMTP_USER")
SMTP_PASSWORD = os.environ.get("SIMHEUT96_SMTP_PASSWORD")
SMTP_FROM = os.environ.get("SIMHEUT96_SMTP_FROM", SMTP_USER or "")

app = FastAPI(title="SimHeut96 - Licences")


# -----------------------------------------------------------------------------
# Base de données
# -----------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _add_column_if_missing(conn, table, column, coltype):
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS codes_generes (
            code TEXT PRIMARY KEY,
            plan TEXT NOT NULL,
            date_generation TEXT NOT NULL,
            date_expiration TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activations (
            code TEXT PRIMARY KEY,
            association_id TEXT NOT NULL,
            association_nom TEXT,
            plan TEXT NOT NULL,
            date_activation TEXT NOT NULL,
            date_expiration TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS revocations (
            code TEXT PRIMARY KEY,
            date_revocation TEXT NOT NULL,
            raison TEXT
        )
    """)
    # Migrations légères pour les bases déjà créées avec l'ancien schéma
    _add_column_if_missing(conn, "codes_generes", "email_destinataire", "TEXT")
    _add_column_if_missing(conn, "codes_generes", "email_envoye", "INTEGER DEFAULT 0")
    conn.commit()
    conn.close()


init_db()


def check_admin(x_admin_password: str | None):
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Mot de passe admin invalide.")


def send_code_email(destinataire: str, code: str, plan: str, date_expiration: str) -> bool:
    """Envoie le code par email. Retourne True si envoyé, False si SMTP non configuré ou erreur."""
    if not (SMTP_HOST and SMTP_USER and SMTP_PASSWORD):
        return False
    try:
        corps = (
            f"Bonjour,\n\n"
            f"Voici votre code d'activation SimHeut96 :\n\n"
            f"    {code}\n\n"
            f"Plan : {lic.PLANS[plan]['label']}\n"
            f"Valable jusqu'au : {date_expiration}\n\n"
            f"Rendez-vous sur la page d'activation de l'application pour l'utiliser.\n\n"
            f"Cordialement,\nL'équipe SimHeut96"
        )
        msg = MIMEText(corps)
        msg["Subject"] = "Votre code d'activation SimHeut96"
        msg["From"] = SMTP_FROM
        msg["To"] = destinataire

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, [destinataire], msg.as_string())
        return True
    except Exception:
        return False


# -----------------------------------------------------------------------------
# Modèles de requête
# -----------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    plan: str
    email_destinataire: str | None = None


class ActivateRequest(BaseModel):
    code: str
    association_id: str
    association_nom: str = ""


class VerifyRequest(BaseModel):
    code: str


class RevokeRequest(BaseModel):
    code: str
    raison: str = ""


# -----------------------------------------------------------------------------
# Endpoints — ADMIN
# -----------------------------------------------------------------------------

@app.post("/api/admin/generate")
def admin_generate(req: GenerateRequest, x_admin_password: str | None = Header(default=None)):
    check_admin(x_admin_password)
    if req.plan not in lic.PLANS:
        raise HTTPException(status_code=400, detail="Plan inconnu.")

    code = lic.generate_license_code(req.plan)
    result = lic.verify_license_code(code)

    email_envoye = False
    if req.email_destinataire:
        email_envoye = send_code_email(req.email_destinataire, code, req.plan, result.date_expiration)

    conn = get_db()
    conn.execute(
        "INSERT INTO codes_generes (code, plan, date_generation, date_expiration, email_destinataire, email_envoye) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (code, req.plan, datetime.now().isoformat(timespec="seconds"), result.date_expiration,
         req.email_destinataire, int(email_envoye)),
    )
    conn.commit()
    conn.close()

    return {
        "code": code,
        "plan": req.plan,
        "label": lic.PLANS[req.plan]["label"],
        "max_membres": lic.PLANS[req.plan]["max_membres"],
        "date_expiration": result.date_expiration,
        "email_envoye": email_envoye,
        "email_configure": bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD),
    }


@app.get("/api/admin/codes")
def admin_list_codes(x_admin_password: str | None = Header(default=None)):
    check_admin(x_admin_password)
    conn = get_db()
    generes = [dict(r) for r in conn.execute(
        "SELECT * FROM codes_generes ORDER BY date_generation DESC").fetchall()]
    actives = {r["code"]: dict(r) for r in conn.execute("SELECT * FROM activations").fetchall()}
    revoques = {r["code"]: dict(r) for r in conn.execute("SELECT * FROM revocations").fetchall()}
    conn.close()

    for g in generes:
        g["activation"] = actives.get(g["code"])
        g["revocation"] = revoques.get(g["code"])
    return {"codes": generes}


@app.post("/api/admin/revoke")
def admin_revoke(req: RevokeRequest, x_admin_password: str | None = Header(default=None)):
    check_admin(x_admin_password)
    code_norm = req.code.strip().upper().replace(" ", "")

    conn = get_db()
    existing = conn.execute("SELECT * FROM revocations WHERE code = ?", (code_norm,)).fetchone()
    if existing:
        conn.close()
        return {"revoque": True, "message": "Ce code était déjà révoqué.", "date_revocation": existing["date_revocation"]}

    conn.execute(
        "INSERT INTO revocations (code, date_revocation, raison) VALUES (?, ?, ?)",
        (code_norm, datetime.now().isoformat(timespec="seconds"), req.raison),
    )
    conn.commit()
    conn.close()
    return {"revoque": True, "message": "Code révoqué. Il ne pourra plus être activé ni utilisé."}


@app.post("/api/admin/unrevoke")
def admin_unrevoke(req: RevokeRequest, x_admin_password: str | None = Header(default=None)):
    check_admin(x_admin_password)
    code_norm = req.code.strip().upper().replace(" ", "")
    conn = get_db()
    conn.execute("DELETE FROM revocations WHERE code = ?", (code_norm,))
    conn.commit()
    conn.close()
    return {"revoque": False, "message": "Révocation annulée."}


@app.get("/api/admin/stats")
def admin_stats(x_admin_password: str | None = Header(default=None)):
    check_admin(x_admin_password)
    conn = get_db()

    total_generes = conn.execute("SELECT COUNT(*) c FROM codes_generes").fetchone()["c"]
    total_revoques = conn.execute("SELECT COUNT(*) c FROM revocations").fetchone()["c"]

    activations = conn.execute("SELECT * FROM activations").fetchall()
    revoques_set = {r["code"] for r in conn.execute("SELECT code FROM revocations").fetchall()}

    today = date.today()
    dans_30_jours = today + timedelta(days=30)

    total_actives = 0
    expirent_bientot = 0
    par_plan = {"ESSAI": 0, "STD": 0, "PRO": 0}

    for a in activations:
        exp = date.fromisoformat(a["date_expiration"])
        est_revoque = a["code"] in revoques_set
        est_expire = exp < today
        if not est_revoque and not est_expire:
            total_actives += 1
            par_plan[a["plan"]] = par_plan.get(a["plan"], 0) + 1
            if exp <= dans_30_jours:
                expirent_bientot += 1

    conn.close()
    return {
        "total_generes": total_generes,
        "total_actives": total_actives,
        "total_revoques": total_revoques,
        "total_non_actives": total_generes - len(activations),
        "expirent_bientot_30j": expirent_bientot,
        "par_plan": par_plan,
    }


# -----------------------------------------------------------------------------
# Endpoints — ASSOCIATIONS (publics)
# -----------------------------------------------------------------------------

@app.post("/api/verify")
def api_verify(req: VerifyRequest):
    result = lic.verify_license_code(req.code)
    return result.__dict__


@app.post("/api/activate")
def api_activate(req: ActivateRequest):
    result = lic.verify_license_code(req.code)
    if not result.valide:
        return result.__dict__

    code_norm = req.code.strip().upper().replace(" ", "")

    conn = get_db()

    revoque = conn.execute("SELECT * FROM revocations WHERE code = ?", (code_norm,)).fetchone()
    if revoque:
        conn.close()
        return {"valide": False, "raison": "Ce code a été révoqué et ne peut plus être activé."}

    existing = conn.execute("SELECT * FROM activations WHERE code = ?", (code_norm,)).fetchone()

    if existing:
        if existing["association_id"] != req.association_id:
            conn.close()
            return {"valide": False, "raison": "Ce code est déjà activé par une autre association."}
        conn.close()
        return {
            "valide": True, "raison": "Déjà activé pour cette association.",
            "plan": result.plan, "max_membres": result.max_membres,
            "date_expiration": result.date_expiration,
        }

    conn.execute(
        "INSERT INTO activations (code, association_id, association_nom, plan, date_activation, date_expiration) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (code_norm, req.association_id, req.association_nom, result.plan,
         datetime.now().isoformat(timespec="seconds"), result.date_expiration),
    )
    conn.commit()
    conn.close()

    return {
        "valide": True, "raison": "Code activé avec succès.",
        "plan": result.plan, "max_membres": result.max_membres,
        "date_expiration": result.date_expiration,
    }


@app.get("/api/status/{association_id}")
def api_status(association_id: str):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM activations WHERE association_id = ? ORDER BY date_activation DESC LIMIT 1",
        (association_id,)).fetchone()
    if not row:
        conn.close()
        return {"actif": False}

    revoque = conn.execute("SELECT * FROM revocations WHERE code = ?", (row["code"],)).fetchone()
    conn.close()

    if revoque:
        return {"actif": False, "raison": "Code révoqué."}

    expire = date.fromisoformat(row["date_expiration"])
    return {
        "actif": date.today() <= expire,
        "plan": row["plan"],
        "date_expiration": row["date_expiration"],
        "association_nom": row["association_nom"],
    }


# -----------------------------------------------------------------------------
# Pages statiques
# -----------------------------------------------------------------------------

@app.get("/")
def home():
    return FileResponse(APP_DIR / "static" / "activate.html")


@app.get("/admin")
def admin_page():
    return FileResponse(APP_DIR / "static" / "admin.html")


app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
