import re
from datetime import datetime

MESES = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
    'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
    'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12
}

CORTES = [
    {"label": "07:00 hrs", "limit_mins": 7 * 60},
    {"label": "11:00 hrs", "limit_mins": 11 * 60},
    {"label": "13:00 hrs", "limit_mins": 13 * 60},
    {"label": "16:00 hrs", "limit_mins": 16 * 60},
    {"label": "19:00 hrs", "limit_mins": 19 * 60},
]

CORTE_ORDER = {c["label"]: i for i, c in enumerate(CORTES)}
CORTE_ORDER["Sin asignar"] = len(CORTES)

ESTATUS_OMS_OPCIONES = ["Pendiente", "Preparado", "Cancelado"]

ESTATUS_EMOJI = {
    "Preparado": "✅",
    "Pendiente":  "⏳",
    "Cancelado":  "🚫",
}

def parse_meli_date(fecha_str):
    """'22 de julio de 2026 03:09 hs.' → datetime"""
    s = str(fecha_str).strip().lower()
    m = re.search(r'(\d{1,2}) de (\w+) de (\d{4})\s+(\d{1,2}):(\d{2})', s)
    if not m:
        return None
    day, mes, year, hour, minute = m.groups()
    month = MESES.get(mes)
    if not month:
        return None
    try:
        return datetime(int(year), month, int(day), int(hour), int(minute))
    except Exception:
        return None

def assign_corte(dt):
    """Asigna el corte operativo según la hora del pedido."""
    if dt is None:
        return "Sin asignar"
    mins = dt.hour * 60 + dt.minute
    for c in CORTES:
        if mins <= c["limit_mins"]:
            return c["label"]
    return "Sin asignar"

def safe_int(val):
    try:
        m = re.search(r'\d+', str(val).split('\n')[0])
        return int(m.group()) if m else 1
    except Exception:
        return 1

def classify_plataforma(estado):
    """Clasifica el estado que viene directo de MeLi (sin tocar Estatus_OMS)."""
    e = str(estado).lower()
    if any(k in e for k in ["cancel", "no despach"]):
        return "Cancelado"
    if any(k in e for k in ["entregado", "enviado", "en camino", "colecta realizada"]):
        return "Enviado"
    return "Activo"

def corte_status_now(corte_label):
    """Devuelve si el corte está cerrado, en proceso o próximo."""
    now_mins = datetime.now().hour * 60 + datetime.now().minute
    c = next((x for x in CORTES if x["label"] == corte_label), None)
    if c is None:
        return "proximo"
    lm = c["limit_mins"]
    if now_mins > lm:
        return "cerrado"
    elif now_mins >= lm - 60:
        return "proceso"
    return "proximo"
