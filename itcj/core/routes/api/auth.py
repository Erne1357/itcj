# routes/api/auth.py
from flask import Blueprint, request, jsonify, make_response, current_app
from ...utils.jwt_tools import encode_jwt, decode_jwt
from ...services.auth_service import authenticate, authenticate_by_username

api_auth_bp = Blueprint("api_auth", __name__)

@api_auth_bp.post("/login")
def api_login():
    data = request.get_json(silent=True) or {}
    raw_id = (data.get("control_number","") or "").strip()  # puede ser 8 dígitos o username
    nip    = (data.get("nip","") or "").strip()

    is_8_digits = raw_id.isdigit() and len(raw_id) == 8

    if not raw_id:
        return jsonify({"error":"invalid_format"}), 400

    # Si son 8 dígitos → alumno por número de control; si no → staff por username
    if is_8_digits:
        user = authenticate(raw_id, nip)
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
        "agendatec_token", token, httponly=True,
        samesite=current_app.config["COOKIE_SAMESITE"],
        secure=current_app.config["COOKIE_SECURE"],
        max_age=current_app.config["JWT_EXPIRES_HOURS"]*3600,
        path="/"
    )
    return resp

@api_auth_bp.get("/me")
def api_me():
    token = request.cookies.get("agendatec_token")
    data = decode_jwt(token) if token else None
    if not data:
        return jsonify({"error":"unauthorized"}), 401
    return jsonify({"user":{
        "id": data["sub"], "role": data["role"],
        "control_number": data.get("cn"), "full_name": data.get("name","")
    }})

@api_auth_bp.post("/logout")
def api_logout():
    resp = make_response({}, 204)
    resp.set_cookie("agendatec_token","",expires=0,httponly=True,
                    samesite=current_app.config["COOKIE_SAMESITE"],
                    secure=current_app.config["COOKIE_SECURE"],
                    path="/")
    return resp
