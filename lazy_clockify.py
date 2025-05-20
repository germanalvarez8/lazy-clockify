import requests
import json
import re
from datetime import datetime, timedelta
import copy

# --- CONFIGURACIÓN ---
GEMINI_API_KEY = "xxx"
CLOCKIFY_API_KEY = "xxx"
CLOCKIFY_WORKSPACE_ID = "xxx"
CLOCKIFY_USER_ID = "xxx"

# --- PROMPT GEMINI ---
# GEMINI_PROMPT = '''Eres un asistente que convierte descripciones de días laborales en registros de tiempo estructurados para Clockify.
# Dado un texto en español que describe actividades, reuniones y tareas con sus horarios o duraciones, responde SOLO con un JSON con la siguiente estructura:

# [
#   {
#     "descripcion": "Descripción clara de la actividad",
#     "hora_inicio": "HH:MM",  // 24h, ej: "09:00"
#     "hora_fin": "HH:MM",     // 24h, ej: "10:30"
#     "duracion": "1:30"       // (opcional, en horas:minutos, si no hay hora_fin)
#   },
#   ...
# ]

# Reglas:
# - Si solo se menciona duración, calcula hora_fin sumando la duración a la hora_inicio.
# - Si no se especifica hora_inicio, asume la anterior hora_fin o 09:00.
# - No debe haber solapamientos.
# - Las horas deben estar en formato 24h.
# - No incluyas texto fuera del JSON.

# Ejemplo 1:
# Texto: "De 9 a 10 reunión con equipo. Luego 2 horas de desarrollo. Almuerzo 1 hora. De 14 a 15:30 revisión de código."
# Respuesta:
# [
#   {"descripcion": "Reunión con equipo", "hora_inicio": "09:00", "hora_fin": "10:00"},
#   {"descripcion": "Desarrollo", "hora_inicio": "10:00", "hora_fin": "12:00"},
#   {"descripcion": "Almuerzo", "hora_inicio": "12:00", "hora_fin": "13:00"},
#   {"descripcion": "Revisión de código", "hora_inicio": "14:00", "hora_fin": "15:30"}
# ]

# Ejemplo 2:
# Texto: "9:30-11:00 soporte. 11 a 12:30 documentación. 13 a 14:30 llamadas."
# Respuesta:
# [
#   {"descripcion": "Soporte", "hora_inicio": "09:30", "hora_fin": "11:00"},
#   {"descripcion": "Documentación", "hora_inicio": "11:00", "hora_fin": "12:30"},
#   {"descripcion": "Llamadas", "hora_inicio": "13:00", "hora_fin": "14:30"}
# ]
# '''

GEMINI_PROMPT = """Eres un asistente que **solo responde con un JSON array válido** sin texto adicional, comentarios o marcas. 

Reglas:
- Formato: [{"start": "HH:MM", "end": "HH:MM", "description": "..."}]
- Horas en formato 24h.
- Si el input es: "Reunión 10-12Am, desarrollo hasta las 15", 
  el output es: [{"start": "10:00", "end": "12:00", "description": "Reunión"}, {"start": "12:00", "end": "15:00", "description": "Desarrollo"}]

Texto a procesar: 
"""

# --- FUNCIONES ---
def build_gemini_prompt(texto_usuario, proyectos):
    proyectos_str = "\n".join([f"- {nombre}: {pid}" for nombre, pid in proyectos.items()])
    prompt = f"""Eres un asistente que SOLO responde con un JSON array válido, sin texto adicional, comentarios ni marcas.\n\nReglas:\n- Formato: [{{'start': 'HH:MM', 'end': 'HH:MM', 'description': '...', 'projectId': '...'}}]\n- projectId debe ser uno de los IDs de proyecto de Clockify listados abajo, eligiendo el más adecuado según la descripción de la actividad.\n- Horas en formato 24h.\n- Si el input es: 'Reunión 10-12Am, desarrollo hasta las 15', el output es: [{{'start': '10:00', 'end': '12:00', 'description': 'Reunión', 'projectId': 'ID_REUNION'}}, {{'start': '12:00', 'end': '15:00', 'description': 'Desarrollo', 'projectId': 'ID_DESARROLLO'}}]\n\nProyectos disponibles (nombre: id):\n{proyectos_str}\n\nTexto a procesar:\n{texto_usuario}"""
    return prompt

def prompt_gemini(texto_usuario, proyectos):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = build_gemini_prompt(texto_usuario, proyectos)
    data = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.0,
            "response_mime_type": "application/json"
        }
    }
    resp = requests.post(url, json=data, headers={"Content-Type": "application/json"})
    if resp.status_code != 200:
        raise Exception(f"Error Gemini API: {resp.status_code} - {resp.text}")
    try:
        response_json = resp.json()
        generated_text = response_json['candidates'][0]['content']['parts'][0]['text']
        clean_json = generated_text.replace("```json", "").replace("```", "").strip()
        print("JSON limpio:", clean_json)  # Debug
        return json.loads(clean_json)
    except (KeyError, json.JSONDecodeError) as e:
        print("Respuesta cruda de Gemini:", generated_text)  # Debug
        raise Exception(f"Error parseando JSON: {str(e)}")

def validar_hora(hora):
    try:
        datetime.strptime(hora, "%H:%M")
        return True
    except Exception:
        return False

def validar_registros(registros):
    # Verifica formato y solapamientos
    prev_fin = None
    for i, r in enumerate(registros):
        if not validar_hora(r["start"]):
            return False, f"Registro {i+1}: start inválida ({r['start']})"
        if not validar_hora(r["end"]):
            return False, f"Registro {i+1}: end inválida ({r['end']})"
        ini = datetime.strptime(r["start"], "%H:%M")
        fin = datetime.strptime(r["end"], "%H:%M")
        if fin <= ini:
            return False, f"Registro {i+1}: end debe ser posterior a start"
        if prev_fin and ini < prev_fin:
            return False, f"Registro {i+1}: solapamiento con el registro anterior"
        prev_fin = fin
    return True, ""

def editar_registros_cli(registros):
    registros = copy.deepcopy(registros)
    for idx, r in enumerate(registros):
        print(f"\nRegistro {idx+1}:")
        print(f"  Descripción: {r['description']}")
        print(f"  Hora inicio: {r['start']}")
        print(f"  Hora fin:    {r['end']}")
        op = input("¿Editar este registro? (s/n): ").strip().lower()
        if op == 's':
            r['description'] = input(f"  Nueva descripción [{r['description']}]: ") or r['description']
            r['start'] = input(f"  Nueva hora inicio [{r['start']}]: ") or r['start']
            r['end'] = input(f"  Nueva hora fin [{r['end']}]: ") or r['end']
    return registros

def enviar_a_clockify(registros, proyectos):
    url = f"https://api.clockify.me/api/v1/workspaces/{CLOCKIFY_WORKSPACE_ID}/time-entries"
    headers = {
        "X-Api-Key": CLOCKIFY_API_KEY,
        "Content-Type": "application/json"
    }
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    exito = True
    for r in registros:
        # Sumar 3 horas para convertir a UTC
        start_dt = datetime.strptime(f"{fecha_hoy} {r['start']}", "%Y-%m-%d %H:%M") + timedelta(hours=3)
        end_dt = datetime.strptime(f"{fecha_hoy} {r['end']}", "%Y-%m-%d %H:%M") + timedelta(hours=3)
        start = start_dt.strftime("%Y-%m-%dT%H:%M:00.000Z")
        end = end_dt.strftime("%Y-%m-%dT%H:%M:00.000Z")
        data = {
            "start": start,
            "end": end,
            "description": r["description"],
            "billable": False,
            "userId": CLOCKIFY_USER_ID,
            "projectId": r.get("projectId")
        }
        resp = requests.post(url, headers=headers, data=json.dumps(data))
        if resp.status_code not in (200, 201):
            print(f"Error al enviar registro '{r['description']}': {resp.status_code} {resp.text}")
            exito = False
    return exito

def get_clockify_projects():
    url = f"https://api.clockify.me/api/v1/workspaces/{CLOCKIFY_WORKSPACE_ID}/projects?clients=5e7ce0702b3f977ab6c13f17"
    headers = {
        "X-Api-Key": CLOCKIFY_API_KEY,
        "Content-Type": "application/json"
    }
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        print(f"Error al obtener proyectos: {resp.status_code} {resp.text}")
        return {}
    proyectos = resp.json()
    # Retorna un dict nombre: id
    return {p['name']: p['id'] for p in proyectos}

def main():
    print("\n=== Lazy Clockify CLI ===\n")
    proyectos = get_clockify_projects()
    if proyectos:
        print("Proyectos disponibles:")
        for nombre, pid in proyectos.items():
            print(f"- {nombre}: {pid}")
    else:
        print("No se pudieron obtener proyectos de Clockify.")
    print("Describe tu día laboral (en una sola línea):")
    texto = input("> ")
    try:
        registros = prompt_gemini(texto, proyectos)
    except Exception as e:
        print(f"Error al procesar con Gemini: {e}")
        return
    # Invertir el dict para buscar nombre por id
    id_a_nombre = {pid: nombre for nombre, pid in proyectos.items()}
    print("\nRegistros generados:")
    for idx, r in enumerate(registros):
        nombre_proyecto = id_a_nombre.get(r.get('projectId'), '-')
        print(f"{idx+1}. {r['description']} | {r['start']} - {r['end']} | Proyecto: {nombre_proyecto}")
    # Permitir edición
    op = input("\n¿Deseas editar algún registro? (s/n): ").strip().lower()
    if op == 's':
        registros = editar_registros_cli(registros)
    # Validar
    ok, msg = validar_registros(registros)
    if not ok:
        print(f"\nError en los registros: {msg}")
        return
    # Confirmar y enviar
    confirm = input("\n¿Enviar a Clockify? (s/n): ").strip().lower()
    if confirm == "s":
        exito = enviar_a_clockify(registros, proyectos)
        if exito:
            print("\n¡Registros enviados con éxito!")
        else:
            print("\nHubo errores al enviar algunos registros.")
    else:
        print("\nOperación cancelada.")

if __name__ == "__main__":
    main()
