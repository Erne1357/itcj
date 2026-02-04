# routes/pages/admin_surveys.py
"""
Páginas de encuestas para AgendaTec.

Incluye: gestión de encuestas y conexión con Microsoft Graph.
"""
from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from itcj.core.utils.decorators import app_required, login_required
from itcj.apps.agendatec.utils.msgraph_mail import (
    acquire_token_silent,
    build_auth_url,
    clear_account_and_cache,
    process_auth_code,
    read_account_info,
)

admin_surveys_pages_bp = Blueprint("admin_surveys_pages", __name__, template_folder="../../templates")


@admin_surveys_pages_bp.get("/")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.surveys.page.list"])
def admin_surveys():
    acct = read_account_info() or {}
    return render_template("agendatec/admin/surveys.html", ms_account=acct)


@admin_surveys_pages_bp.get("/auth/login")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.surveys.api.send"])
def ms_login():
    state = "surveys"
    return redirect(build_auth_url(state))


@admin_surveys_pages_bp.get("/auth/callback")
def ms_callback():
    code = request.args.get("code")
    if not code:
        return "Falta ?code=", 400
    r = process_auth_code(code)
    if r.get("error"):
        return f"Error MSAL: {r['error_description']}", 400
    return redirect(url_for("agendatec_pages.admin_surveys_pages.admin_surveys"))


@admin_surveys_pages_bp.post("/auth/logout")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.surveys.api.send"])
def ms_logout():
    clear_account_and_cache()
    return jsonify({"ok": True})


@admin_surveys_pages_bp.get("/auth/status")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.surveys.api.send"])
def ms_status():
    token = acquire_token_silent()
    acct = read_account_info()
    return jsonify({"connected": bool(token), "account": acct})
