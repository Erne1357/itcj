# routes/api/auth.py
from flask import Blueprint, request, jsonify, make_response, current_app
from itcj.core.utils.jwt_tools import encode_jwt, decode_jwt
from itcj.core.services.auth_service import authenticate, authenticate_by_username
from itcj.core.utils.decorators import api_auth_required

api_auth_bp = Blueprint("api_auth", __name__)

@api_auth_bp.post("/login")
def api_login():
    data = request.get_json(silent=True) or {}
    raw_id = (data.get("control_number","") or "").strip()  # puede ser número de control o username
    nip    = (data.get("nip","") or "").strip()

    import re
    # Número de control: 8 dígitos puros, o 9-10 chars alfanuméricos que inician con letra (posgrado/traslado)
    is_control_number = bool(re.match(r'^(?:\d{8}|[A-Za-z]\d{7,9})$', raw_id))

    if not raw_id:
        return jsonify({"error":"invalid_format"}), 400

    # Si parece número de control → alumno; si no → staff por username
    if is_control_number:
        user = authenticate(raw_id.upper(), nip)
    else:
        user = authenticate_by_username(raw_id, nip)

    if not user:
        return jsonify({"error":"invalid_credentials"}), 401

    token = encode_jwt(
        {"sub": str(user["id"]), "role": user["role"],
         "cn": user.get("control_number"), "name": user["full_name"]},
        hours=current_app.config["JWT_EXPIRES_HOURS"]
    )
    resp = make_response({"user":{"id":user["id"],"role":user["role"],"full_name":user["full_name"]}})
    resp.set_cookie(
        "itcj_token", token, httponly=True,
        samesite=current_app.config["COOKIE_SAMESITE"],
        secure=current_app.config["COOKIE_SECURE"],
        max_age=current_app.config["JWT_EXPIRES_HOURS"]*3600,
        path="/"
    )
    return resp

@api_auth_bp.get("/me")
@api_auth_required
def api_me():
    token = request.cookies.get("itcj_token")
    data = decode_jwt(token) if token else None
    if not data:
        return jsonify({"error":"unauthorized"}), 401
    return jsonify({"user":{
        "id": data["sub"], "role": data["role"],
        "control_number": data.get("cn"), "full_name": data.get("name","")
    }})

@api_auth_bp.post("/logout")
@api_auth_required
def api_logout():
    resp = make_response({}, 204)
    resp.set_cookie("itcj_token","",expires=0,httponly=True,
                    samesite=current_app.config["COOKIE_SAMESITE"],
                    secure=current_app.config["COOKIE_SECURE"],
                    path="/")
    return resp
