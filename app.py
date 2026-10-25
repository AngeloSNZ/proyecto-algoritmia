from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
from pathlib import Path
from datetime import date
import sqlite3
import uuid

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"
DB_PATH = BASE_DIR / "equipos.db"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app = Flask(__name__)
app.secret_key = "cambia-esta-clave-para-tu-proyecto"
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # máximo 8 MB por solicitud
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS equipos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL,
            marca TEXT,
            modelo TEXT,
            serial TEXT,
            fabricante TEXT,
            ubicacion TEXT,
            responsable TEXT,
            fecha_adquisicion TEXT,
            garantia_hasta TEXT,
            estado TEXT NOT NULL DEFAULT 'Operativo',
            observaciones TEXT,
            foto TEXT,
            creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS mantenimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipo_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            tipo TEXT NOT NULL,
            responsable TEXT,
            descripcion TEXT NOT NULL,
            proximo_mantenimiento TEXT,
            FOREIGN KEY (equipo_id) REFERENCES equipos(id) ON DELETE CASCADE
        );
        """)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_photo(file):
    if not file or not file.filename:
        return None
    if not allowed_file(file.filename):
        raise ValueError("La fotografía debe ser JPG, JPEG, PNG o WEBP.")
    ext = secure_filename(file.filename).rsplit(".", 1)[1].lower()
    name = f"{uuid.uuid4().hex}.{ext}"
    file.save(UPLOAD_FOLDER / name)
    return name


@app.route("/")
def index():
    with get_db() as db:
        equipos = db.execute("""
            SELECT e.*,
            (SELECT COUNT(*) FROM mantenimientos m WHERE m.equipo_id = e.id) AS total_mantenimientos
            FROM equipos e ORDER BY e.id
        """).fetchall()
    return render_template("index.html", equipos=equipos, capacidad=5)


@app.route("/nuevo", methods=["GET", "POST"])
def nuevo():
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) FROM equipos").fetchone()[0]
    if total >= 5:
        flash("Ya registraste los cinco equipos permitidos en este proyecto.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        data = request.form
        required = ["codigo", "nombre"]
        if any(not data.get(field, "").strip() for field in required):
            flash("Completa como mínimo el código y el nombre del equipo.", "error")
            return render_template("form.html", equipo=data, hoy=date.today().isoformat(), modo="nuevo")

        foto = None
        try:
            foto = save_photo(request.files.get("foto"))
            with get_db() as db:
                db.execute("""
                    INSERT INTO equipos
                    (codigo, nombre, marca, modelo, serial, fabricante, ubicacion, responsable,
                     fecha_adquisicion, garantia_hasta, estado, observaciones, foto)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    data["codigo"].strip(), data["nombre"].strip(), data.get("marca", "").strip(),
                    data.get("modelo", "").strip(), data.get("serial", "").strip(),
                    data.get("fabricante", "").strip(), data.get("ubicacion", "").strip(),
                    data.get("responsable", "").strip(), data.get("fecha_adquisicion") or None,
                    data.get("garantia_hasta") or None, data.get("estado", "Operativo"),
                    data.get("observaciones", "").strip(), foto
                ))
            flash("Equipo registrado correctamente.", "success")
            return redirect(url_for("index"))
        except sqlite3.IntegrityError:
            if foto:
                (UPLOAD_FOLDER / foto).unlink(missing_ok=True)
            flash("Ese código de inventario ya existe. Escribe uno diferente.", "error")
        except ValueError as exc:
            flash(str(exc), "error")
        except Exception:
            if foto:
                (UPLOAD_FOLDER / foto).unlink(missing_ok=True)
            flash("No se pudo guardar el equipo. Revisa los datos e inténtalo de nuevo.", "error")
        return render_template("form.html", equipo=data, hoy=date.today().isoformat(), modo="nuevo")

    return render_template("form.html", equipo={}, hoy=date.today().isoformat(), modo="nuevo")


@app.route("/equipo/<int:equipo_id>")
def detalle(equipo_id):
    with get_db() as db:
        equipo = db.execute("SELECT * FROM equipos WHERE id = ?", (equipo_id,)).fetchone()
        mantenimientos = db.execute(
            "SELECT * FROM mantenimientos WHERE equipo_id = ? ORDER BY fecha DESC, id DESC",
            (equipo_id,)
        ).fetchall()
    if not equipo:
        flash("No se encontró ese equipo.", "error")
        return redirect(url_for("index"))
    return render_template("detalle.html", equipo=equipo, mantenimientos=mantenimientos, hoy=date.today().isoformat())


@app.route("/equipo/<int:equipo_id>/mantenimiento", methods=["POST"])
def agregar_mantenimiento(equipo_id):
    data = request.form
    if not data.get("fecha") or not data.get("tipo") or not data.get("descripcion", "").strip():
        flash("Completa la fecha, el tipo y la descripción del mantenimiento.", "error")
        return redirect(url_for("detalle", equipo_id=equipo_id))
    with get_db() as db:
        exists = db.execute("SELECT id FROM equipos WHERE id = ?", (equipo_id,)).fetchone()
        if not exists:
            flash("No se encontró ese equipo.", "error")
            return redirect(url_for("index"))
        db.execute("""
            INSERT INTO mantenimientos
            (equipo_id, fecha, tipo, responsable, descripcion, proximo_mantenimiento)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            equipo_id, data["fecha"], data["tipo"], data.get("responsable", "").strip(),
            data["descripcion"].strip(), data.get("proximo_mantenimiento") or None
        ))
    flash("Mantenimiento agregado al historial.", "success")
    return redirect(url_for("detalle", equipo_id=equipo_id))


@app.route("/equipo/<int:equipo_id>/estado", methods=["POST"])
def cambiar_estado(equipo_id):
    estado = request.form.get("estado", "")
    estados_validos = {"Operativo", "En mantenimiento", "Fuera de servicio", "Dado de baja"}
    if estado not in estados_validos:
        flash("Selecciona un estado válido.", "error")
    else:
        with get_db() as db:
            db.execute("UPDATE equipos SET estado = ? WHERE id = ?", (estado, equipo_id))
        flash("Estado actualizado.", "success")
    return redirect(url_for("detalle", equipo_id=equipo_id))


@app.errorhandler(413)
def too_large(_error):
    flash("La imagen es demasiado grande. Usa una fotografía de máximo 8 MB.", "error")
    return redirect(request.referrer or url_for("index"))


init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
