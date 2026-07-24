import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json
from logic import (
    parse_meli_date, assign_corte, safe_int,
    classify_plataforma, CORTE_ORDER, ESTATUS_OMS_OPCIONES
)

SHEET_ID  = "1J_x0us47fxOccFeFbVxl6jT3h7M0v31r246bmyLQjl8"
OMS_COL   = "Estatus_OMS"
TAB_HOY   = "Ventas MX"
TAB_MAN   = "Ventas MX MAÑANA"

# ── Autenticación ─────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def get_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    info = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)

def get_ws(tab):
    return get_client().open_by_key(SHEET_ID).worksheet(tab)

# ── Columna Estatus_OMS ───────────────────────────────────────────────────────
def ensure_oms_col(ws):
    """Crea columna Estatus_OMS si no existe. Retorna índice 1-based."""
    headers = ws.row_values(1)
    if OMS_COL in headers:
        return headers.index(OMS_COL) + 1
    col_idx = len(headers) + 1
    ws.update_cell(1, col_idx, OMS_COL)
    return col_idx

def update_estatus(tab, sheet_row, new_status):
    """Escribe nuevo Estatus_OMS en la fila indicada del Sheet."""
    ws  = get_ws(tab)
    col = ensure_oms_col(ws)
    ws.update_cell(sheet_row, col, new_status)

# ── Carga y procesamiento MeLi ────────────────────────────────────────────────
@st.cache_data(ttl=180, show_spinner=False)
def load_meli_raw(tab):
    return get_ws(tab).get_all_values()

def _col_idx(headers, *keywords):
    for kw in keywords:
        for i, h in enumerate(headers):
            if kw.lower() in h.lower():
                return i
    return None

def process_meli(tab):
    """
    Retorna:
        orders  → lista de dicts con cada pedido
        row_map → { order_id: sheet_row_number }
    """
    raw = load_meli_raw(tab)
    if len(raw) < 2:
        return [], {}

    headers, rows = raw[0], raw[1:]

    # Columnas por nombre (tolerante a variaciones)
    c = {
        "id":     _col_idx(headers, "# de venta"),
        "fecha":  _col_idx(headers, "Fecha de venta"),
        "estado": _col_idx(headers, "Estado"),
        "desc":   _col_idx(headers, "Descripción del estado"),
        "paq":    _col_idx(headers, "Paquete de varios"),
        "sku":    _col_idx(headers, "SKU"),
        "titulo": _col_idx(headers, "Título de la publicación", "titulo"),
        "uds":    _col_idx(headers, "Unidades"),
        "oms":    _col_idx(headers, OMS_COL),
    }

    def get(row, key, default=""):
        idx = c.get(key)
        if idx is None or idx >= len(row):
            return default
        return str(row[idx]).strip()

    orders  = []
    row_map = {}
    i = 0

    while i < len(rows):
        row      = rows[i]
        order_id = get(row, "id")
        if not order_id:
            i += 1
            continue

        fecha_str   = get(row, "fecha")
        estado      = get(row, "estado")
        desc        = get(row, "desc")
        es_paq      = get(row, "paq").lower()
        sku         = get(row, "sku")
        titulo      = get(row, "titulo")
        uds         = safe_int(get(row, "uds", "1"))
        estatus_oms = get(row, "oms") or "Pendiente"

        dt         = parse_meli_date(fecha_str)
        corte      = assign_corte(dt)
        plat_clas  = classify_plataforma(estado)
        sheet_row  = i + 2   # +1 encabezado, +1 base-1

        row_map[order_id] = sheet_row

        if es_paq in ["sí", "si", "yes"]:
            # Cabecera de paquete — leer partidas hijas inmediatamente abajo
            partidas = []
            i += 1
            while i < len(rows):
                child     = rows[i]
                child_id  = get(child, "id")
                child_paq = get(child, "paq").lower()
                if not child_id or child_paq in ["sí", "si", "yes"]:
                    break
                partidas.append({
                    "id":     child_id,
                    "sku":    get(child, "sku"),
                    "titulo": get(child, "titulo"),
                    "uds":    safe_int(get(child, "uds", "1")),
                    "estado": get(child, "estado"),
                })
                row_map[child_id] = i + 2
                i += 1

            total_uds = sum(p["uds"] for p in partidas) or uds
            orders.append({
                "tab": tab, "id": order_id, "fecha_str": fecha_str, "dt": dt,
                "estado": estado, "desc": desc, "es_paquete": True,
                "sku": "—", "titulo": f"PAQUETE ({len(partidas)} SKUs)",
                "uds": total_uds, "corte": corte, "plat_clas": plat_clas,
                "estatus_oms": estatus_oms, "partidas": partidas,
                "sheet_row": sheet_row,
            })
        else:
            orders.append({
                "tab": tab, "id": order_id, "fecha_str": fecha_str, "dt": dt,
                "estado": estado, "desc": desc, "es_paquete": False,
                "sku": sku, "titulo": titulo, "uds": uds, "corte": corte,
                "plat_clas": plat_clas, "estatus_oms": estatus_oms,
                "partidas": [], "sheet_row": sheet_row,
            })
            i += 1

    # Ordenar por hora de creación: más viejos primero (mayor prioridad)
    orders.sort(key=lambda o: o["dt"] if o["dt"] else __import__('datetime').datetime.max)
    return orders, row_map
