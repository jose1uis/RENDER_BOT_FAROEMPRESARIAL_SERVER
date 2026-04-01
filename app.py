import os
from datetime import timedelta

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
)
from openai import OpenAI
from werkzeug.security import generate_password_hash, check_password_hash

# -------------------------
# App init
# -------------------------
app = Flask(__name__)

# -------------------------
# Configuración DB
# -------------------------
database_url = os.getenv("DATABASE_URL", "")

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# -------------------------
# JWT CONFIG (SEGURO)
# -------------------------
jwt_secret = os.getenv("JWT_SECRET_KEY")

if not jwt_secret:
    raise ValueError("❌ JWT_SECRET_KEY no está configurado en variables de entorno")

app.config["JWT_SECRET_KEY"] = jwt_secret
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=12)

# -------------------------
# CORS (DEV + PROD)
# -------------------------
allowed_origins = os.getenv(
    "FRONTEND_ORIGINS",
    "http://localhost:5500,http://127.0.0.1:5500,https://faroempresarial.co,https://www.faroempresarial.co"
).split(",")

CORS(app, resources={
    r"/api/*": {
        "origins": allowed_origins
    }
})

# -------------------------
# DB + JWT + OpenAI
# -------------------------
db = SQLAlchemy(app)
jwt = JWTManager(app)

openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("❌ OPENAI_API_KEY no configurado")

client = OpenAI(api_key=openai_api_key)
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# -------------------------
# Models
# -------------------------
class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)


class ContentBlock(db.Model):
    __tablename__ = "content_blocks"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    label = db.Column(db.String(150), nullable=False)
    value = db.Column(db.Text, nullable=False)

# -------------------------
# Helpers
# -------------------------
def seed_default_content():
    defaults = [
        ("vip_title", "Título principal", "Panel VIP FARO"),
        ("vip_subtitle", "Subtítulo principal", "Espacio exclusivo para socios."),
        ("vip_notice", "Aviso principal", "Habla con el asesor IA."),
        ("vip_chat_placeholder", "Placeholder", "Escribe aquí..."),
    ]

    for key, label, value in defaults:
        existing = ContentBlock.query.filter_by(key=key).first()
        if not existing:
            db.session.add(ContentBlock(key=key, label=label, value=value))

    db.session.commit()


def seed_superadmin():
    email = os.getenv("SUPERADMIN_EMAIL")
    password = os.getenv("SUPERADMIN_PASSWORD")
    name = os.getenv("SUPERADMIN_NAME", "Superadmin FARO")

    if not email or not password:
        print("⚠️ No hay superadmin configurado")
        return

    existing = User.query.filter_by(email=email.lower().strip()).first()
    if existing:
        return

    admin = User(
        full_name=name,
        email=email.lower().strip(),
        is_admin=True,
        is_active=True,
    )
    admin.set_password(password)

    db.session.add(admin)
    db.session.commit()

    print("✅ Superadmin creado")


def current_user():
    identity = get_jwt_identity()
    return User.query.get(identity["user_id"])


def admin_required():
    user = current_user()
    if not user or not user.is_admin:
        return jsonify({"error": "Acceso restringido"}), 403
    return None

# -------------------------
# Bootstrap
# -------------------------
with app.app_context():
    db.create_all()
    seed_default_content()
    seed_superadmin()

# -------------------------
# Health
# -------------------------
@app.get("/api/health")
def health():
    return jsonify({"ok": True})

# -------------------------
# Auth
# -------------------------
@app.post("/api/login")
def login():
    try:
        data = request.get_json() or {}
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")

        if not email or not password:
            return jsonify({"error": "Email y contraseña obligatorios"}), 400

        user = User.query.filter_by(email=email, is_active=True).first()

        if not user or not user.check_password(password):
            return jsonify({"error": "Credenciales incorrectas"}), 401

        token = create_access_token(identity={
            "user_id": user.id,
            "email": user.email,
            "is_admin": user.is_admin,
        })

        return jsonify({
            "token": token,
            "user": {
                "id": user.id,
                "full_name": user.full_name,
                "email": user.email,
                "is_admin": user.is_admin,
            }
        })

    except Exception as e:
        print("ERROR LOGIN:", e)
        return jsonify({"error": str(e)}), 500


@app.get("/api/me")
@jwt_required()
def me():
    user = current_user()
    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 404

    return jsonify({
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
    })

# -------------------------
# Content
# -------------------------
@app.get("/api/content")
@jwt_required()
def get_content():
    blocks = ContentBlock.query.all()

    return jsonify([
        {
            "id": b.id,
            "key": b.key,
            "label": b.label,
            "value": b.value,
        }
        for b in blocks
    ])


@app.put("/api/content/<string:key>")
@jwt_required()
def update_content(key):
    unauthorized = admin_required()
    if unauthorized:
        return unauthorized

    data = request.get_json() or {}
    value = data.get("value", "").strip()

    if not value:
        return jsonify({"error": "Contenido vacío"}), 400

    block = ContentBlock.query.filter_by(key=key).first()
    if not block:
        return jsonify({"error": "No encontrado"}), 404

    block.value = value
    db.session.commit()

    return jsonify({"ok": True})

# -------------------------
# Users
# -------------------------
@app.get("/api/admin/users")
@jwt_required()
def list_users():
    unauthorized = admin_required()
    if unauthorized:
        return unauthorized

    users = User.query.all()

    return jsonify([
        {
            "id": u.id,
            "full_name": u.full_name,
            "email": u.email,
            "is_admin": u.is_admin,
            "is_active": u.is_active,
        }
        for u in users
    ])


@app.post("/api/admin/users")
@jwt_required()
def create_user():
    unauthorized = admin_required()
    if unauthorized:
        return unauthorized

    data = request.get_json() or {}

    full_name = data.get("full_name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()
    is_admin = bool(data.get("is_admin", False))

    if not full_name or not email or not password:
        return jsonify({"error": "Datos incompletos"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email ya existe"}), 409

    user = User(
        full_name=full_name,
        email=email,
        is_admin=is_admin,
        is_active=True,
    )
    user.set_password(password)

    db.session.add(user)
    db.session.commit()

    return jsonify({"ok": True})

# -------------------------
# Chat IA
# -------------------------
@app.post("/api/chat")
@jwt_required()
def chat():
    try:
        user = current_user()
        data = request.get_json() or {}
        mensaje = data.get("mensaje", "").strip()

        if not mensaje:
            return jsonify({"error": "Mensaje vacío"}), 400

        system_prompt = f"""
Eres un asesor empresarial experto de FARO Empresarial SAS.
Respondes en español.
Tono profesional, claro y estratégico.
Usuario: {user.full_name}
"""

        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": mensaje},
            ],
        )

        return jsonify({
            "respuesta": response.choices[0].message.content
        })

    except Exception as e:
        print("ERROR CHAT:", e)
        return jsonify({"error": str(e)}), 500

# -------------------------
# Security headers
# -------------------------
@app.after_request
def after_request(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
