import streamlit as st
from datetime import datetime
import pandas as pd
from logic import (
    CORTES, CORTE_ORDER, ESTATUS_EMOJI,
    ESTATUS_OMS_OPCIONES, corte_status_now
)
from data import process_meli, update_estatus, load_meli_raw, TAB_HOY, TAB_MAN

# ── Configuración ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="OMS | ILLUX",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("## 📦 OMS — Gestión de Pedidos | ILLUX Tlanepantla")
st.caption(f"🏭 Almacén: Tlanepantla · {datetime.now().strftime('%A %d/%m/%Y  %H:%M hrs')}")

# ── Controles superiores ──────────────────────────────────────────────────────
col_act, col_vista = st.columns([1, 5])
with col_act:
    if st.button("↺ Actualizar", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
with col_vista:
    vista = st.radio(
        "Vista",
        ["📅 Hoy (Ventas MX)", "📆 Mañana (Ventas MX MAÑANA)"],
        horizontal=True,
        label_visibility="collapsed",
    )

tab_activo = TAB_HOY if "Hoy" in vista else TAB_MAN

# ── Carga de datos ────────────────────────────────────────────────────────────
try:
    with st.spinner("Cargando datos de Mercado Libre..."):
        orders, row_map = process_meli(tab_activo)
except Exception as e:
    st.error(f"❌ Error al cargar datos: {e}")
    st.stop()

if not orders:
    st.info("No se encontraron pedidos en esta pestaña.")
    st.stop()

# ── KPIs globales ─────────────────────────────────────────────────────────────
activos  = [o for o in orders if o["plat_clas"] != "Cancelado"]
cancelados = [o for o in orders if o["plat_clas"] == "Cancelado"]
preparados = [o for o in activos if o["estatus_oms"] == "Preparado"]
pendientes = [o for o in activos if o["estatus_oms"] == "Pendiente"]

total_ped = len(orders)
total_uds = sum(o["uds"] for o in activos)
n_prep    = len(preparados)
n_pend    = len(pendientes)
n_canc    = len(cancelados)
pct       = round(n_prep / (n_prep + n_pend) * 100) if (n_prep + n_pend) > 0 else 0

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("📦 Total pedidos", total_ped)
k2.metric("📊 Uds a surtir",  total_uds)
k3.metric("✅ Preparados",    n_prep)
k4.metric("⏳ Pendientes",    n_pend)
k5.metric("🚫 Cancelados",    n_canc)
st.progress(
    pct / 100,
    text=f"Avance de preparación: **{pct}%** ({n_prep} de {n_prep + n_pend} pedidos activos)"
)

st.divider()

# ── Secciones por corte (acumulativo) ─────────────────────────────────────────
all_corte_labels = [c["label"] for c in CORTES] + ["Sin asignar"]

acum_prep = 0
acum_pend = 0
acum_uds  = 0

for corte_label in all_corte_labels:
    corte_orders = [o for o in orders if o["corte"] == corte_label]
    if not corte_orders:
        continue

    c_activos   = [o for o in corte_orders if o["plat_clas"] != "Cancelado"]
    c_prep      = sum(1 for o in corte_orders if o["estatus_oms"] == "Preparado")
    c_pend      = sum(1 for o in corte_orders if o["estatus_oms"] == "Pendiente")
    c_canc      = sum(1 for o in corte_orders if o["plat_clas"] == "Cancelado")
    c_uds       = sum(o["uds"] for o in c_activos)
    c_nuevos    = len(corte_orders)   # pedidos que cayeron en este corte

    acum_prep += c_prep
    acum_pend += c_pend
    acum_uds  += c_uds

    if corte_label == "Sin asignar":
        status_txt = "📋 Sin corte identificado"
        is_open    = False
    else:
        status_key = corte_status_now(corte_label)
        status_txt = {
            "cerrado": "✔️ Cerrado",
            "proceso": "⏳ **En proceso**",
            "proximo": "🔜 Próximo",
        }[status_key]
        is_open = status_key == "proceso"

    header = (
        f"🕐 **{corte_label}**  {status_txt}  │  "
        f"+{c_nuevos} pedidos · {c_uds} uds  │  "
        f"✅ {c_prep}  ⏳ {c_pend}  🚫 {c_canc}"
    )

    with st.expander(header, expanded=is_open):

        # Acumulado hasta este corte
        st.info(
            f"🔢 **Acumulado al cierre de este corte:**  "
            f"✅ {acum_prep} preparados · "
            f"⏳ {acum_pend} pendientes · "
            f"📦 {acum_uds} uds totales"
        )

        st.markdown("---")

        # ── Tabla con control de Estatus_OMS ─────────────────────────────────
        for o in corte_orders:
            col_info, col_ctrl = st.columns([5, 2])

            clas_emoji = ESTATUS_EMOJI.get(o["estatus_oms"], "⏳")
            paq_badge  = "📦 " if o["es_paquete"] else ""
            canc_badge = " 🚫" if o["plat_clas"] == "Cancelado" else ""

            with col_info:
                st.markdown(
                    f"**{paq_badge}{o['id']}**{canc_badge}  \n"
                    f"🕒 `{o['fecha_str']}`  │  "
                    f"📌 `{o['sku']}`  │  "
                    f"📦 **{o['uds']} uds**  \n"
                    f"_{o['titulo'][:80]}{'…' if len(o['titulo']) > 80 else ''}_"
                )
                # Partidas del paquete
                if o["es_paquete"] and o["partidas"]:
                    for p in o["partidas"]:
                        st.markdown(
                            f"&nbsp;&nbsp;&nbsp;↳ `{p['id']}` · "
                            f"`{p['sku']}` · {p['uds']} uds"
                        )

            with col_ctrl:
                if o["plat_clas"] == "Cancelado":
                    st.error("🚫 CANCELADO (MeLi)")
                else:
                    key = f"sel_{tab_activo}_{o['id']}"
                    idx = ESTATUS_OMS_OPCIONES.index(o["estatus_oms"]) \
                          if o["estatus_oms"] in ESTATUS_OMS_OPCIONES else 0
                    nuevo = st.selectbox(
                        "Estado OMS",
                        ESTATUS_OMS_OPCIONES,
                        index=idx,
                        key=key,
                        label_visibility="collapsed",
                    )
                    if nuevo != o["estatus_oms"]:
                        try:
                            update_estatus(tab_activo, o["sheet_row"], nuevo)
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al actualizar: {e}")

            st.divider()
