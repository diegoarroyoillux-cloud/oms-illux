import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime
import json
import re

# ── CONFIG ────────────────────────────────────────────────
st.set_page_config(
    page_title="OMS | ILLUX Tlanepantla",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed"
)

SHEET_ID = "1J_x0us47fxOccFeFbVxl6jT3h7M0v31r246bmyLQjl8"

CORTES = [
    {"label": "07:00 hrs", "mins": 7 * 60},
    {"label": "11:00 hrs", "mins": 11 * 60},
    {"label": "13:00 hrs", "mins": 13 * 60},
    {"label": "16:00 hrs", "mins": 16 * 60},
    {"label": "19:00 hrs", "mins": 19 * 60},
]

# ── AUTENTICACIÓN ─────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def get_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

@st.cache_data(ttl=300, show_spinner=False)
def load_sheet(tab):
    client = get_client()
    ws = client.open_by_key(SHEET_ID).worksheet(tab)
    data = ws.get_all_values()
    if len(data) < 2:
        return pd.DataFrame()
    return pd.DataFrame(data[1:], columns=data[0])

@st.cache_data(ttl=300, show_spinner="Actualizando datos...")
def load_all():
    return {
        "meli_hoy": load_sheet("Ventas MX"),
        "meli_man": load_sheet("Ventas MX MAÑANA"),
        "amazon":   load_sheet("AMAZON"),
        "easyship": load_sheet("EASY SHIP"),
        "flex":     load_sheet("AMAZON FLEX"),
    }

# ── HELPERS ───────────────────────────────────────────────
def safe_int(val):
    try:
        m = re.search(r'\d+', str(val).split('\n')[0])
        return int(m.group()) if m else 1
    except:
        return 1

def find_col(cols, *keywords):
    for kw in keywords:
        for c in cols:
            if kw.lower() in c.lower():
                return c
    return None

def extract_time_mins(text):
    t = str(text)
    # "colecta de las HH:MM"
    m = re.search(r'colecta de las (\d{1,2}):(\d{2})', t, re.I)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    # "a las HH:MM"
    m = re.search(r'a las (\d{1,2}):(\d{2})', t, re.I)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    # "HH:MM AM/PM" (Easy Ship slots)
    m = re.search(r'(\d{1,2}):(\d{2})\s*(AM|PM)', t, re.I)
    if m:
        h, mn, p = int(m.group(1)), int(m.group(2)), m.group(3).upper()
        if p == 'PM' and h != 12: h += 12
        if p == 'AM' and h == 12: h = 0
        return h * 60 + mn
    # trailing HH:MM — FLEX dates like "2026-07-22 14:00"
    m = re.search(r'(\d{1,2}):(\d{2})\s*$', t.strip())
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None

def assign_corte(mins):
    if mins is None:
        return "Sin asignar"
    for c in CORTES:
        if mins <= c["mins"]:
            return c["label"]
    return "Sin asignar"

def classify_estado(estado, preparado_col=None):
    e = str(estado).lower()
    if any(k in e for k in ["cancel", "no despach"]):
        return "cancelado"
    if preparado_col and str(preparado_col).lower() in ["sí", "si", "yes", "true", "1"]:
        return "preparado"
    if any(k in e for k in ["preparado", "listo", "en camino", "entregado", "enviado", "easy ship"]):
        return "preparado"
    return "pendiente"

# ── PROCESAMIENTO MELI ────────────────────────────────────
def process_meli(df, tab):
    orders = []
    if df.empty:
        return orders

    cols = list(df.columns)
    c_id     = find_col(cols, "# de venta", "venta")
    c_fecha  = find_col(cols, "Fecha de venta", "fecha")
    c_estado = find_col(cols, "Estado")
    c_desc   = find_col(cols, "Descripción del estado", "descripci")
    c_paquete= find_col(cols, "Paquete de varios")
    c_sku    = find_col(cols, "SKU")
    c_titulo = find_col(cols, "Título de la publicación", "título", "titulo")
    c_uds    = find_col(cols, "Unidades")

    i = 0
    while i < len(df):
        row = df.iloc[i]
        order_id = str(row.get(c_id, "")).strip() if c_id else ""
        if not order_id:
            i += 1
            continue

        estado  = str(row.get(c_estado,  "")).strip() if c_estado  else ""
        desc    = str(row.get(c_desc,    "")).strip() if c_desc    else ""
        es_paq  = str(row.get(c_paquete, "")).strip().lower() if c_paquete else "no"
        sku     = str(row.get(c_sku,     "")).strip() if c_sku     else ""
        titulo  = str(row.get(c_titulo,  "")).strip() if c_titulo  else ""
        fecha   = str(row.get(c_fecha,   "")).strip() if c_fecha   else ""
        uds     = safe_int(row.get(c_uds, "1")) if c_uds else 1

        clasificacion = classify_estado(estado)
        time_mins     = extract_time_mins(desc)
        corte         = assign_corte(time_mins)

        if es_paq in ["sí", "si", "yes"]:
            # Cabecera de paquete — recolectar partidas hijas
            partidas = []
            i += 1
            while i < len(df):
                child     = df.iloc[i]
                child_id  = str(child.get(c_id,     "")).strip() if c_id     else ""
                child_paq = str(child.get(c_paquete,"")).strip().lower() if c_paquete else "no"
                if not child_id or child_paq in ["sí", "si", "yes"]:
                    break
                partidas.append({
                    "id":     child_id,
                    "sku":    str(child.get(c_sku,    "")).strip() if c_sku    else "",
                    "titulo": str(child.get(c_titulo, "")).strip() if c_titulo else "",
                    "uds":    safe_int(child.get(c_uds, "1")) if c_uds else 1,
                    "estado": str(child.get(c_estado, "")).strip() if c_estado else "",
                })
                i += 1
            total_uds = sum(p["uds"] for p in partidas) or uds
            orders.append({
                "tab": tab, "canal": "MeLi", "paqueteria": "MeLi",
                "id": order_id, "fecha": fecha, "estado": estado, "desc": desc,
                "sku": "—", "titulo": f"📦 PAQUETE ({len(partidas)} SKUs)",
                "uds": total_uds, "corte": corte, "clasificacion": clasificacion,
                "es_paquete": True, "partidas": partidas,
            })
        else:
            orders.append({
                "tab": tab, "canal": "MeLi", "paqueteria": "MeLi",
                "id": order_id, "fecha": fecha, "estado": estado, "desc": desc,
                "sku": sku, "titulo": titulo, "uds": uds, "corte": corte,
                "clasificacion": clasificacion, "es_paquete": False, "partidas": [],
            })
            i += 1
    return orders

# ── PROCESAMIENTO AMAZON ──────────────────────────────────
def process_amazon(df_amazon, df_easyship):
    orders = []
    if df_amazon.empty:
        return orders

    easy_map = {}
    if not df_easyship.empty:
        for _, row in df_easyship.iterrows():
            oid  = str(row.get("order-id",    "")).strip()
            slot = str(row.get("pickup-slot", "")).strip()
            if oid:
                easy_map[oid] = slot

    for _, row in df_amazon.iterrows():
        order_id = str(row.get("order-id", "")).strip()
        if not order_id:
            continue

        es_easy    = order_id in easy_map
        paqueteria = "Amazon Logistics" if es_easy else "DHL"
        slot       = easy_map.get(order_id, "")
        time_mins  = extract_time_mins(slot) if es_easy else None
        corte      = assign_corte(time_mins)
        estado     = "Easy Ship" if es_easy else "Pendiente"

        orders.append({
            "tab": "hoy", "canal": "Amazon", "paqueteria": paqueteria,
            "id": order_id,
            "fecha": str(row.get("Fecha envío", "")).strip(),
            "estado": estado, "desc": slot,
            "sku":    str(row.get("sku",          "")).strip(),
            "titulo": str(row.get("product-name", "")).strip(),
            "uds": safe_int(row.get("quantity-purchased", "1")),
            "corte": corte, "clasificacion": classify_estado(estado),
            "es_paquete": False, "partidas": [],
        })
    return orders

# ── PROCESAMIENTO FLEX ────────────────────────────────────
def process_flex(df):
    orders = []
    if df.empty:
        return orders

    cols = list(df.columns)
    c_id   = find_col(cols, "pedido del cliente", "número de pedido")
    c_sku  = find_col(cols, "SKU")
    c_tit  = find_col(cols, "título", "titulo")
    c_uds  = find_col(cols, "Unidades")
    c_est  = find_col(cols, "Estado")
    c_fenv = find_col(cols, "prevista", "fecha")
    c_prep = find_col(cols, "Preparado")

    for _, row in df.iterrows():
        order_id = str(row.get(c_id,  "")).strip() if c_id  else ""
        sku      = str(row.get(c_sku, "")).strip() if c_sku else ""
        if not order_id and not sku:
            continue

        fecha     = str(row.get(c_fenv, "")).strip() if c_fenv else ""
        estado    = str(row.get(c_est,  "")).strip() if c_est  else ""
        preparado = str(row.get(c_prep, "")).strip() if c_prep else ""
        time_mins = extract_time_mins(fecha)

        orders.append({
            "tab": "hoy", "canal": "FLEX", "paqueteria": "FLEX",
            "id": order_id, "fecha": fecha, "estado": estado, "desc": fecha,
            "sku": sku,
            "titulo": str(row.get(c_tit, "")).strip() if c_tit else "",
            "uds": safe_int(row.get(c_uds, "1")) if c_uds else 1,
            "corte": assign_corte(time_mins),
            "clasificacion": classify_estado(estado, preparado_col=preparado),
            "es_paquete": False, "partidas": [],
        })
    return orders

# ── CANAL CONFIG ──────────────────────────────────────────
CANAL_CONFIG = {
    "MeLi":             {"emoji": "🟡", "label": "Mercado Libre"},
    "Amazon_DHL":       {"emoji": "🔴", "label": "Amazon DHL"},
    "Amazon_Logistics": {"emoji": "🔵", "label": "Amazon Logistics"},
    "FLEX":             {"emoji": "🟣", "label": "Amazon FLEX"},
}

def get_canal_key(o):
    if o["canal"] == "Amazon":
        return "Amazon_DHL" if o["paqueteria"] == "DHL" else "Amazon_Logistics"
    return o["canal"]

def corte_status(corte_label):
    now_mins = datetime.now().hour * 60 + datetime.now().minute
    try:
        h = int(corte_label.split(":")[0])
        cm = h * 60
        if now_mins > cm + 30:
            return "cerrado", "✔️ Cerrado"
        elif now_mins >= cm - 60:
            return "proceso", "⏳ En proceso"
        else:
            return "proximo", "🔜 Próximo"
    except:
        return "proximo", ""

CLAS_EMOJI = {"preparado": "✅", "pendiente": "⏳", "cancelado": "🚫"}

# ── HEADER ────────────────────────────────────────────────
st.markdown("## 📦 OMS — Control de Pedidos | ILLUX Tlanepantla")
st.caption(f"🏭 Almacén: Tlanepantla · {datetime.now().strftime('%A %d/%m/%Y  %H:%M hrs')}")

col_ref, col_vista, col_canal = st.columns([1, 3, 4])
with col_ref:
    if st.button("↺ Actualizar", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
with col_vista:
    vista = st.radio("Vista", ["📅 Hoy", "📆 Mañana"], horizontal=True, label_visibility="collapsed")
with col_canal:
    filtro_canal = st.multiselect(
        "Canal", ["MeLi", "Amazon", "FLEX"],
        default=["MeLi", "Amazon", "FLEX"],
        label_visibility="collapsed"
    )

# ── CARGA DE DATOS ────────────────────────────────────────
try:
    with st.spinner("Cargando datos..."):
        sheets = load_all()
    all_orders = (
        process_meli(sheets["meli_hoy"], "hoy") +
        process_meli(sheets["meli_man"], "manana") +
        process_amazon(sheets["amazon"], sheets["easyship"]) +
        process_flex(sheets["flex"])
    )
except Exception as e:
    st.error(f"❌ Error al cargar datos: {e}")
    st.stop()

# Filtrar por vista y canal
current_tab = "hoy" if "Hoy" in vista else "manana"
orders = [o for o in all_orders if o["tab"] == current_tab and o["canal"] in filtro_canal]

# ── KPIs GLOBALES ─────────────────────────────────────────
total_ped = len(orders)
total_uds = sum(o["uds"] for o in orders if o["clasificacion"] != "cancelado")
n_prep    = sum(1 for o in orders if o["clasificacion"] == "preparado")
n_pend    = sum(1 for o in orders if o["clasificacion"] == "pendiente")
n_canc    = sum(1 for o in orders if o["clasificacion"] == "cancelado")

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("📦 Total pedidos",    total_ped)
k2.metric("📊 Uds a surtir",     total_uds)
k3.metric("✅ Preparados",       n_prep)
k4.metric("⏳ Pendientes",       n_pend)
k5.metric("🚫 Cancelados",       n_canc)

pct_prep = round(n_prep / (n_prep + n_pend) * 100) if (n_prep + n_pend) > 0 else 0
st.progress(pct_prep / 100, text=f"Avance de preparación: **{pct_prep}%** ({n_prep} de {n_prep + n_pend} pedidos activos)")

st.divider()

# ── SECCIONES POR CORTE ───────────────────────────────────
all_corte_labels = [c["label"] for c in CORTES] + ["Sin asignar"]
acum_prep = 0
acum_pend = 0
acum_canc = 0
acum_uds  = 0

for corte_label in all_corte_labels:
    corte_orders = [o for o in orders if o["corte"] == corte_label]
    if not corte_orders:
        continue

    c_prep = sum(1 for o in corte_orders if o["clasificacion"] == "preparado")
    c_pend = sum(1 for o in corte_orders if o["clasificacion"] == "pendiente")
    c_canc = sum(1 for o in corte_orders if o["clasificacion"] == "cancelado")
    c_uds  = sum(o["uds"] for o in corte_orders if o["clasificacion"] != "cancelado")

    acum_prep += c_prep
    acum_pend += c_pend
    acum_canc += c_canc
    acum_uds  += c_uds

    if corte_label == "Sin asignar":
        status_key, status_txt = "proximo", "📋 Sin corte asignado"
        is_active = False
    else:
        status_key, status_txt = corte_status(corte_label)
        is_active = status_key == "proceso"

    header = (
        f"🕐 **{corte_label}**  {status_txt}  │  "
        f"📦 {len(corte_orders)} pedidos · {c_uds} uds  │  "
        f"✅ {c_prep} preparados  ⏳ {c_pend} pendientes  🚫 {c_canc} cancelados"
    )

    with st.expander(header, expanded=is_active):

        # ── Resumen por canal ──────────────────────────────
        canal_groups = {}
        for o in corte_orders:
            k = get_canal_key(o)
            canal_groups.setdefault(k, []).append(o)

        col1, col2, col3, col4 = st.columns(4)
        for idx, (ckey, cfg) in enumerate(CANAL_CONFIG.items()):
            with [col1, col2, col3, col4][idx]:
                c_ords = canal_groups.get(ckey, [])
                if c_ords:
                    cp = sum(1 for x in c_ords if x["clasificacion"] == "preparado")
                    cn = sum(1 for x in c_ords if x["clasificacion"] == "pendiente")
                    cc = sum(1 for x in c_ords if x["clasificacion"] == "cancelado")
                    cu = sum(x["uds"] for x in c_ords if x["clasificacion"] != "cancelado")
                    st.markdown(f"**{cfg['emoji']} {cfg['label']}**")
                    st.markdown(f"✅ `{cp}` preparados")
                    st.markdown(f"⏳ `{cn}` pendientes")
                    st.markdown(f"🚫 `{cc}` cancelados")
                    st.markdown(f"📦 `{len(c_ords)}` pedidos · `{cu}` uds")
                else:
                    st.markdown(f"**{cfg['emoji']} {cfg['label']}**")
                    st.caption("Sin pedidos")

        # ── Acumulado ──────────────────────────────────────
        st.info(
            f"🔢 **Acumulado hasta este corte:**  "
            f"✅ {acum_prep} preparados · "
            f"⏳ {acum_pend} pendientes · "
            f"📦 {acum_uds} uds totales"
        )

        st.divider()

        # ── Tabla de detalle ───────────────────────────────
        rows = []
        for o in corte_orders:
            ckey = get_canal_key(o)
            cfg  = CANAL_CONFIG.get(ckey, {"emoji": "", "label": o["canal"]})
            rows.append({
                "Canal":      f"{cfg['emoji']} {cfg['label']}",
                "# Pedido":   o["id"],
                "SKU":        o["sku"],
                "Producto":   o["titulo"][:60] + "…" if len(o["titulo"]) > 60 else o["titulo"],
                "Uds":        o["uds"],
                "Estado":     f"{CLAS_EMOJI.get(o['clasificacion'],'')} {o['estado']}",
                "Fecha/Slot": o["fecha"],
            })
            if o["es_paquete"]:
                for p in o["partidas"]:
                    p_clas = classify_estado(p["estado"])
                    rows.append({
                        "Canal":      "",
                        "# Pedido":   f"   ↳ {p['id']}",
                        "SKU":        p["sku"],
                        "Producto":   p["titulo"][:55] + "…" if len(p["titulo"]) > 55 else p["titulo"],
                        "Uds":        p["uds"],
                        "Estado":     f"{CLAS_EMOJI.get(p_clas,'')} {p['estado']}",
                        "Fecha/Slot": "",
                    })

        if rows:
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Uds":    st.column_config.NumberColumn(width="small"),
                    "Estado": st.column_config.TextColumn(width="medium"),
                    "Canal":  st.column_config.TextColumn(width="medium"),
                }
            )

st.caption(
    f"🔄 Auto-refresh cada 5 min · "
    f"Última carga: {datetime.now().strftime('%H:%M:%S')}"
)
