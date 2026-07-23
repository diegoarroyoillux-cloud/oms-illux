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

CORTES_MINUTOS = [
    ("07:00 hrs", 0,       7*60),
    ("11:00 hrs", 7*60+1,  11*60),
    ("13:00 hrs", 11*60+1, 13*60),
    ("16:00 hrs", 13*60+1, 16*60),
    ("19:00 hrs", 16*60+1, 19*60),
    ("Sin corte",  19*60+1, 99999),
]

# ── AUTENTICACIÓN ─────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly"
    ]
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

# ── CARGA DE DATOS ────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner="Actualizando datos...")
def load_sheet(tab_name):
    client = get_gspread_client()
    sh = client.open_by_key(SHEET_ID)
    ws = sh.worksheet(tab_name)
    data = ws.get_all_values()
    if len(data) < 2:
        return pd.DataFrame()
    df = pd.DataFrame(data[1:], columns=data[0])
    return df

def load_all():
    meli_hoy = load_sheet("Ventas MX")
    meli_man = load_sheet("Ventas MX MAÑANA")
    amazon   = load_sheet("AMAZON")
    easyship = load_sheet("EASY SHIP")
    flex     = load_sheet("AMAZON FLEX")
    return meli_hoy, meli_man, amazon, easyship, flex

# ── HELPERS ───────────────────────────────────────────────
def getcol(cols_dict, key):
    for c, orig in cols_dict.items():
        if key.lower() in c:
            return orig
    return None

def safe_int(val):
    """Extrae el primer número entero de cualquier valor."""
    try:
        m = re.search(r'\d+', str(val).split('\n')[0])
        return int(m.group()) if m else 1
    except:
        return 1

def parse_time_desc(desc):
    m = re.search(r'a las (\d{1,2}):(\d{2})', str(desc), re.IGNORECASE)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m2 = re.search(r'las (\d{1,2}):(\d{2})', str(desc), re.IGNORECASE)
    if m2:
        return int(m2.group(1)) * 60 + int(m2.group(2))
    return None

def parse_pickup_slot(slot):
    m = re.search(r'(\d{1,2}):(\d{2})\s*(AM|PM)', str(slot), re.IGNORECASE)
    if m:
        h, mn, period = int(m.group(1)), int(m.group(2)), m.group(3).upper()
        if period == 'PM' and h != 12: h += 12
        if period == 'AM' and h == 12: h = 0
        return h * 60 + mn
    return None

def parse_flex_time(dt_str):
    m = re.search(r'(\d{1,2}):(\d{2})$', str(dt_str).strip())
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None

def assign_corte(mins):
    if mins is None:
        return "Sin corte"
    for label, lo, hi in CORTES_MINUTOS:
        if mins <= hi:
            return label
    return "Sin corte"

def is_cancelado(estado):
    return "cancel" in str(estado).lower()

def corte_status(corte_label):
    now = datetime.now()
    now_mins = now.hour * 60 + now.minute
    if corte_label in ("Sin corte", "Mañana"):
        return "proximo"
    try:
        h = int(corte_label.split(":")[0])
        corte_mins = h * 60
        if now_mins > corte_mins:
            return "cerrado"
        elif now_mins >= corte_mins - 60:
            return "proceso"
        else:
            return "proximo"
    except:
        return "proximo"

# ── PROCESAMIENTO MELI ────────────────────────────────────
def process_meli(df, tab):
    orders = []
    if df.empty:
        return orders

    cols = {c.lower(): c for c in df.columns}

    col_id     = getcol(cols, "venta") or getcol(cols, "pedido")
    col_estado = getcol(cols, "estado")
    col_desc   = getcol(cols, "descripci")
    col_sku    = getcol(cols, "sku")
    col_titulo = getcol(cols, "tulo") or getcol(cols, "titulo")
    col_uds    = getcol(cols, "unidades") or getcol(cols, "cantidad")
    col_fecha  = getcol(cols, "fecha")

    i = 0
    while i < len(df):
        row = df.iloc[i]
        order_id = str(row.get(col_id, "")).strip() if col_id else ""
        if not order_id:
            i += 1
            continue

        estado = str(row.get(col_estado, "")).strip() if col_estado else ""
        desc   = str(row.get(col_desc,   "")).strip() if col_desc   else ""
        sku    = str(row.get(col_sku,    "")).strip() if col_sku    else ""
        titulo = str(row.get(col_titulo, "")).strip() if col_titulo else ""
        uds    = str(row.get(col_uds,    "1")).strip() if col_uds   else "1"
        fecha  = str(row.get(col_fecha,  "")).strip() if col_fecha  else ""

        es_paquete = "paquete de" in estado.lower()

        if es_paquete:
            partidas = []
            i += 1
            while i < len(df):
                child        = df.iloc[i]
                child_id     = str(child.get(col_id,     "")).strip() if col_id     else ""
                child_estado = str(child.get(col_estado, "")).strip() if col_estado else ""
                if not child_id or "paquete de" in child_estado.lower():
                    break
                partidas.append({
                    "id":     child_id,
                    "sku":    str(child.get(col_sku,    "")).strip() if col_sku    else "",
                    "titulo": str(child.get(col_titulo, "")).strip() if col_titulo else "",
                    "uds":    safe_int(child.get(col_uds, "1")) if col_uds else 1,
                    "estado": child_estado,
                })
                i += 1
            total_uds = sum(p["uds"] for p in partidas)
            time_mins = parse_time_desc(desc)
            orders.append({
                "tab": tab, "canal": "MeLi", "paqueteria": "MeLi",
                "id": order_id, "fecha": fecha, "estado": estado,
                "sku": "—", "titulo": f"📦 PAQUETE ({len(partidas)} SKUs)",
                "uds": total_uds, "corte": assign_corte(time_mins),
                "es_paquete": True, "partidas": partidas,
            })
        else:
            time_mins = parse_time_desc(desc)
            uds_int   = safe_int(uds)
            orders.append({
                "tab": tab, "canal": "MeLi", "paqueteria": "MeLi",
                "id": order_id, "fecha": fecha, "estado": estado,
                "sku": sku, "titulo": titulo, "uds": uds_int,
                "corte": assign_corte(time_mins),
                "es_paquete": False, "partidas": [],
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
        cols_es = {c.lower(): c for c in df_easyship.columns}
        c_esid  = getcol(cols_es, "order-id") or getcol(cols_es, "order id")
        c_slot  = getcol(cols_es, "pickup-slot") or getcol(cols_es, "pickup slot")
        if c_esid:
            for _, row in df_easyship.iterrows():
                oid = str(row.get(c_esid, "")).strip()
                if oid:
                    easy_map[oid] = str(row.get(c_slot, "")).strip() if c_slot else ""

    cols_a = {c.lower(): c for c in df_amazon.columns}
    c_id   = getcol(cols_a, "order-id") or getcol(cols_a, "order id")
    c_sku  = getcol(cols_a, "sku")
    c_prod = getcol(cols_a, "product-name") or getcol(cols_a, "product name")
    c_uds  = getcol(cols_a, "quantity-purchased") or getcol(cols_a, "quantity")
    c_fenv = getcol(cols_a, "fecha env") or getcol(cols_a, "latest-ship-date")

    for _, row in df_amazon.iterrows():
        if not c_id: continue
        order_id = str(row.get(c_id, "")).strip()
        if not order_id: continue

        es_easy    = order_id in easy_map
        paqueteria = "Amazon Logistics" if es_easy else "DHL"
        slot       = easy_map.get(order_id, "")
        time_mins  = parse_pickup_slot(slot) if es_easy else None

        uds = safe_int(row.get(c_uds, "1"))

        orders.append({
            "tab": "hoy", "canal": "Amazon", "paqueteria": paqueteria,
            "id": order_id,
            "fecha": str(row.get(c_fenv, "")).strip() if c_fenv else "",
            "estado": "Easy Ship" if es_easy else "Pendiente",
            "sku":    str(row.get(c_sku,  "")).strip() if c_sku  else "",
            "titulo": str(row.get(c_prod, "")).strip() if c_prod else "",
            "uds": uds, "corte": assign_corte(time_mins),
            "es_paquete": False, "partidas": [],
        })
    return orders

# ── PROCESAMIENTO FLEX ────────────────────────────────────
def process_flex(df):
    orders = []
    if df.empty:
        return orders

    cols  = {c.lower(): c for c in df.columns}
    c_id  = getcol(cols, "pedido del cliente") or getcol(cols, "mero de pedido")
    c_sku = getcol(cols, "sku")
    c_tit = getcol(cols, "tulo") or getcol(cols, "titulo")
    c_uds = getcol(cols, "unidades") or getcol(cols, "cantidad")
    c_est = getcol(cols, "estado")
    c_fenv= getcol(cols, "prevista") or getcol(cols, "fecha")

    for _, row in df.iterrows():
        order_id = str(row.get(c_id,  "")).strip() if c_id  else ""
        sku      = str(row.get(c_sku, "")).strip() if c_sku else ""
        if not order_id and not sku:
            continue

        fecha     = str(row.get(c_fenv, "")).strip() if c_fenv else ""
        time_mins = parse_flex_time(fecha)
        uds       = safe_int(row.get(c_uds, "1"))

        orders.append({
            "tab": "hoy", "canal": "FLEX", "paqueteria": "FLEX",
            "id": order_id, "fecha": fecha,
            "estado": str(row.get(c_est, "")).strip() if c_est else "",
            "sku": sku,
            "titulo": str(row.get(c_tit, "")).strip() if c_tit else "",
            "uds": uds, "corte": assign_corte(time_mins),
            "es_paquete": False, "partidas": [],
        })
    return orders

# ── UI ────────────────────────────────────────────────────
st.markdown("## 📦 OMS — Gestión de Pedidos ILLUX Tlanepantla")

col_refresh, col_tab, col_f1, col_f2, col_f3 = st.columns([1, 2, 2, 2, 2])
with col_refresh:
    if st.button("↺ Actualizar", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
with col_tab:
    tab_sel = st.radio("Vista", ["📅 Hoy", "📆 Mañana"], horizontal=True, label_visibility="collapsed")
with col_f1:
    filtro_canal = st.selectbox("Canal", ["Todos", "MeLi", "Amazon", "FLEX"], label_visibility="collapsed")
with col_f2:
    filtro_paq = st.selectbox("Paquetería", ["Todas", "DHL", "Amazon Logistics", "FLEX", "MeLi"], label_visibility="collapsed")
with col_f3:
    filtro_est = st.selectbox("Estado", ["Todos", "Activos", "Cancelados"], label_visibility="collapsed")

# Carga de datos
with st.spinner("Cargando datos..."):
    try:
        meli_hoy_df, meli_man_df, amazon_df, easyship_df, flex_df = load_all()
        all_orders = (
            process_meli(meli_hoy_df, "hoy") +
            process_meli(meli_man_df, "manana") +
            process_amazon(amazon_df, easyship_df) +
            process_flex(flex_df)
        )
        load_ok = True
    except Exception as e:
        st.error(f"❌ Error al cargar datos: {e}")
        load_ok = False

if not load_ok:
    st.stop()

# Aplicar filtros
current_tab = "hoy" if "Hoy" in tab_sel else "manana"
filtered = [o for o in all_orders if o["tab"] == current_tab]
if filtro_canal != "Todos":     filtered = [o for o in filtered if o["canal"]      == filtro_canal]
if filtro_paq   != "Todas":     filtered = [o for o in filtered if o["paqueteria"] == filtro_paq]
if filtro_est   == "Activos":   filtered = [o for o in filtered if not is_cancelado(o["estado"])]
if filtro_est   == "Cancelados":filtered = [o for o in filtered if is_cancelado(o["estado"])]

# KPIs
activos    = [o for o in filtered if not is_cancelado(o["estado"])]
cancels    = [o for o in filtered if is_cancelado(o["estado"])]
preparados = [o for o in activos if any(k in o["estado"].lower() for k in ["preparado","listo","easy ship"])]
total_uds  = sum(o["uds"] for o in activos)

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total pedidos",     len(filtered))
k2.metric("Unidades a surtir", total_uds)
k3.metric("Preparados",        len(preparados))
k4.metric("Pendientes",        len(activos) - len(preparados))
k5.metric("Cancelados",        len(cancels))

st.divider()

# Agrupar por corte
CORTE_ORDER = [c[0] for c in CORTES_MINUTOS] + ["Mañana"]
by_corte = {c: [] for c in CORTE_ORDER}
for o in filtered:
    c = o.get("corte", "Sin corte")
    if c not in by_corte:
        by_corte[c] = []
    by_corte[c].append(o)

CANAL_EMOJI = {"MeLi": "🟡", "Amazon": "🔵", "FLEX": "🟣"}
PAQ_LABEL   = {"DHL": "🔴 DHL", "Amazon Logistics": "🔵 AMZ Log.", "FLEX": "🟣 FLEX", "MeLi": "🟡 MeLi"}
STATUS_MAP  = {"cancel": "🚫", "preparado": "✅", "listo": "✅", "easy ship": "✅", "paquete de": "📦"}

def fmt_estado(e):
    for k, emoji in STATUS_MAP.items():
        if k in str(e).lower():
            return f"{emoji} {e}"
    return e

# Renderizar por corte
for corte_label in CORTE_ORDER:
    ords = by_corte.get(corte_label, [])
    if not ords:
        continue

    status     = corte_status(corte_label)
    status_txt = {"cerrado": "✔ Cerrado", "proceso": "⏳ En proceso", "proximo": "⏰ Próximo"}.get(status, "")
    uds_corte  = sum(o["uds"] for o in ords if not is_cancelado(o["estado"]))
    expanded   = status == "proceso"

    with st.expander(
        f"🕐 Corte {corte_label}  |  {status_txt}  |  {len(ords)} pedidos · {uds_corte} uds",
        expanded=expanded
    ):
        rows = []
        for o in ords:
            rows.append({
                "# Pedido":   o["id"],
                "Canal":      CANAL_EMOJI.get(o["canal"], "") + " " + o["canal"],
                "Paquetería": PAQ_LABEL.get(o["paqueteria"], o["paqueteria"]),
                "SKU":        o["sku"],
                "Producto":   o["titulo"][:65] + "..." if len(o["titulo"]) > 65 else o["titulo"],
                "Uds":        o["uds"],
                "Estado":     fmt_estado(o["estado"]),
                "Fecha/Hora": o["fecha"],
            })
            if o["es_paquete"]:
                for p in o["partidas"]:
                    rows.append({
                        "# Pedido":   f"   ↳ {p['id']}",
                        "Canal":      "",
                        "Paquetería": "",
                        "SKU":        p["sku"],
                        "Producto":   p["titulo"][:60] + "..." if len(p["titulo"]) > 60 else p["titulo"],
                        "Uds":        p["uds"],
                        "Estado":     fmt_estado(p["estado"]),
                        "Fecha/Hora": "",
                    })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Uds":    st.column_config.NumberColumn(width="small"),
                "Estado": st.column_config.TextColumn(width="medium"),
            }
        )

st.caption(
    f"🏭 Almacén: TLANEPANTLA · "
    f"Última actualización: {datetime.now().strftime('%H:%M:%S')} · "
    f"Auto-refresh cada 5 min"
)
