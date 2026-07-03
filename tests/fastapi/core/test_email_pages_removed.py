"""F1a: los AJAX de email viven en /api/core/v2/email — las rutas de página ya no existen."""


def test_page_status_endpoint_removed(app_client, auth_headers):
    resp = app_client.get(
        "/itcj/config/email/auth/status?app=helpdesk",
        headers=auth_headers, follow_redirects=False,
    )
    assert resp.status_code == 404


def test_page_logout_endpoint_removed(app_client, auth_headers):
    resp = app_client.post(
        "/itcj/config/email/auth/logout?app=helpdesk",
        headers=auth_headers, follow_redirects=False,
    )
    assert resp.status_code == 404
