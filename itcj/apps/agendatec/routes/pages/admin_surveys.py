# routes/pages/admin_surveys.py
from flask import Blueprint, render_template, redirect, request, url_for, jsonify, g
from itcj.core.utils.decorators import login_required,role_required_page, app_required
from itcj.core.utils.msgraph_mail import build_auth_url, process_auth_code, acquire_token_silent, clear_account_and_cache, read_account_info

admin_surveys_pages = Blueprint("admin_surveys_pages", __name__, template_folder="../../templates")

@admin_surveys_pages.get("/admin/surveys")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.surveys.view"])
def admin_surveys():
    acct = read_account_info() or {}
    # Muestra estado de conexión y botones
    return render_template("agendatec/admin/surveys.html", ms_account=acct)

@admin_surveys_pages.get("/auth/ms/login")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.surveys.manage"])
def ms_login():
    # Puedes generar un state si quieres validarlo a la vuelta
    state = "surveys"
    return redirect(build_auth_url(state))

@admin_surveys_pages.get("/auth/ms/callback")
def ms_callback():
    code = request.args.get("code")
    if not code:
        return "Falta ?code=", 400
    r = process_auth_code(code)
    if r.get("error"):
        return f"Error MSAL: {r['error_description']}", 400
    return redirect(url_for("agendatec_pages.admin_surveys_pages.admin_surveys"))

@admin_surveys_pages.post("/auth/ms/logout")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.surveys.manage"])
def ms_logout():
    clear_account_and_cache()
    return jsonify({"ok": True})

@admin_surveys_pages.get("/auth/ms/status")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.surveys.manage"])
def ms_status():
    # ¿tengo token silencioso? (indica que hay sesión viva)
    token = acquire_token_silent()
    acct = read_account_info()
    return jsonify({"connected": bool(token), "account": acct})
