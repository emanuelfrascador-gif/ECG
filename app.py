import io
import os
import base64
import json
import time
import math
import textwrap
from flask import Flask, request, send_file
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types

app = Flask(__name__)
# BLINDAJE DE MEMORIA PARA RENDER: Limitado a 10MB para evitar SIGKILL
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
client = genai.Client(api_key=api_key) if api_key else genai.Client()

def obtener_riesgo_real(texto_riesgo):
    v = str(texto_riesgo).lower()
    if 'cr' in v: return 'critico'
    if 'alt' in v: return 'alto'
    if 'mod' in v: return 'moderado'
    if 'baj' in v: return 'bajo'
    return 'indeterminado'

def cargar_fuente(tamanio, negrita=False):
    fuentes_normales = ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf", "FreeSans.ttf", "seguiemj.ttf"]
    fuentes_negrita = ["arialbd.ttf", "Arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "FreeSansBold.ttf", "seguisb.ttf"]
    lista = fuentes_negrita if negrita else fuentes_normales
    for f in lista:
        try: return ImageFont.truetype(f, int(tamanio))
        except: pass
    return ImageFont.load_default()

def safe_float(val, default=50.0):
    try:
        if val is None: return default
        return float(str(val).replace('%', '').strip())
    except Exception:
        return default

# ESCÁNER DE TINTA ORIGINAL (Preciso y sin fallos geométricos)
def snap_to_ecg_trace_smart(img, cx, cy, w_orig, h_orig):
    gray = img.convert('L')
    pixels = gray.load()
    
    rx = max(1, int(w_orig * 0.02))
    ry = max(1, int(h_orig * 0.08))
    
    best_x, best_y = cx, cy
    min_score = float('inf')
    
    for i in range(max(1, cx - rx), min(w_orig - 1, cx + rx)):
        for j in range(max(1, cy - ry), min(h_orig - 1, cy + ry)):
            val = pixels[i, j]
            if val < 130: 
                vecinos_oscuros = 0
                for di in [-1, 0, 1]:
                    for dj in [-1, 0, 1]:
                        if pixels[i+di, j+dj] < 150:
                            vecinos_oscuros += 1
                            
                if vecinos_oscuros >= 3:
                    dist_sq = (i - cx)**2 + (j - cy)**2
                    score = dist_sq + (val * 2) 
                    
                    if score < min_score:
                        min_score = score
                        best_x, best_y = i, j
                        
    if min_score != float('inf'):
        return best_x, best_y
    return cx, cy

# FLECHAS NEGRAS FINAS PARA ESPEJOS
def draw_dotted_arrow(draw, pt1, pt2, color, escala):
    x1, y1 = pt1
    x2, y2 = pt2
    dist = math.hypot(x2 - x1, y2 - y1)
    if dist < 15 * escala: return 
    
    angle = math.atan2(y2 - y1, x2 - x1)
    dash_length = 4 * escala
    width = max(1, int(1.2 * escala))
    
    d = 0
    while d < dist:
        end_d = min(d + dash_length, dist)
        start_x = x1 + math.cos(angle) * d
        start_y = y1 + math.sin(angle) * d
        end_x = x1 + math.cos(angle) * end_d
        end_y = y1 + math.sin(angle) * end_d
        draw.line([(start_x, start_y), (end_x, end_y)], fill=color, width=width)
        d += dash_length * 2.5
        
    head_len = 6 * escala
    head_angle = math.pi / 7
    
    h1_x1 = x1 + head_len * math.cos(angle + head_angle)
    h1_y1 = y1 + head_len * math.sin(angle + head_angle)
    h1_x2 = x1 + head_len * math.cos(angle - head_angle)
    h1_y2 = y1 + head_len * math.sin(angle - head_angle)
    draw.line([(x1, y1), (h1_x1, h1_y1)], fill=color, width=width)
    draw.line([(x1, y1), (h1_x2, h1_y2)], fill=color, width=width)
    
    h2_x1 = x2 - head_len * math.cos(angle + head_angle)
    h2_y1 = y2 - head_len * math.sin(angle + head_angle)
    h2_x2 = x2 - head_len * math.cos(angle - head_angle)
    h2_y2 = y2 - head_len * math.sin(angle - head_angle)
    draw.line([(x2, y2), (h2_x1, h2_y1)], fill=color, width=width)
    draw.line([(x2, y2), (h2_x2, h2_y2)], fill=color, width=width)

@app.route("/", methods=["GET"])
def home():
    return "API de Procesamiento de ECG Activa - Versión Profesional Pura"

@app.route("/analizar", methods=["POST"])
def analizar_ecg():
    datos_crudos = request.args.get('datos', 'Paciente sin datos clínicos proporcionados.')
    
    ecg_orig = None
    data_cruda = request.get_data()
    try:
        if data_cruda: ecg_orig = Image.open(io.BytesIO(data_cruda)).convert("RGB")
    except: pass

    if not ecg_orig:
        try:
            data = request.get_json(silent=True, force=True)
            imagen_base64 = data.get("image") or data.get("Image") if isinstance(data, dict) else None
            if not imagen_base64:
                cuerpo_crudo = data_cruda.decode("utf-8", errors="ignore").strip()
                imagen_base64 = cuerpo_crudo.replace('{"image":"', '').replace('{"Image":"', '').replace('image=', '').rstrip('"}').strip()
            image_data = base64.b64decode(imagen_base64)
            ecg_orig = Image.open(io.BytesIO(image_data)).convert("RGB")
        except: pass

    if not ecg_orig:
        return {"error": "No se recibió ninguna imagen válida."}, 400

    w_orig, h_orig = ecg_orig.size

    # PROMPT MAESTRO PROFESIONAL (Sin diálogos escritos, criterios en ítems con justificación de positividad/negatividad)
    prompt_maestro = (
        "INSTRUCCIÓN SUPREMA: Actúa como el Mejor Cardiólogo del Mundo. Analiza el ECG con rigor científico absoluto, onda por onda, segmento por segmento e intervalo por intervalo, con memoria fotográfica de todos los manuales de cardiología.\n"
        f"DATOS CLÍNICOS DEL PACIENTE: {datos_crudos}\n\n"
        "REGLAS INQUEBRANTABLES:\n"
        "1. CERO ALUCINACIONES: Diagnostica ÚNICAMENTE lo que ves de forma objetiva en el trazado. Está prohibido generalizar o repetir diagnósticos preestablecidos.\n"
        "2. CRITERIOS Y METODOLOGÍA ('tecnicas_utilizadas'): Lista de forma directa y profesional los criterios cardiológicos evaluados (ej. Wellens, Sgarbossa, Brugada, Sokolow-Lyon, Cornell, Cabrera, etc.), indicando brevemente si resultaron positivos o negativos y por qué (ej: '• Criterios de Sgarbossa: Negativos (ausencia de discordancia excesiva)'). Sin diálogos conversacionales, directo al análisis técnico.\n"
        "3. ETIOLOGÍA CRÍTICAMENTE FUNDADA: Realiza una búsqueda etiológica profunda basada en la clínica y el trazado eléctrico.\n"
        "4. TRATAMIENTO Y CONDUCTA SAC ('manejo_sac'): Orden jerárquico estricto. Primero estudios complementarios o de urgencia, luego fármacos. CADA FÁRMACO DEBE LLEVAR: Fármaco + Dosis exacta + (Justificación clínica detallada entre paréntesis).\n"
        "5. SINCRONIZACIÓN TOTAL DE MARCAS: Todo hallazgo patológico descrito en 'lista_hallazgos' DEBE tener obligatoriamente su marca gráfica correspondiente en la imagen, y viceversa. No puede haber hallazgos sin marcar.\n"
        "6. PRECISIÓN ESPACIAL: Las coordenadas (x_porcentaje, y_porcentaje) deben posarse exactamente sobre el latido anómalo en la cuadrícula, nunca sobre las etiquetas de texto.\n"
        "7. ESPEJOS ANATÓMICOS: Si hay lesión recíproca o en espejo, asigna el mismo número entero en 'id_espejo' (ej. 1) para unirlas automáticamente con una línea punteada.\n"
        "8. CONFIANZA: 'confianza_ia' en porcentaje entero (ej: '98%').\n\n"
        "DEVUELVE EXCLUSIVAMENTE UN JSON VÁLIDO CON ESTA ESTRUCTURA:\n"
        "{\n"
        '  "es_ecg": true,\n'
        '  "cables_invertidos": false,\n'
        '  "anamnesis_redactada": "...",\n'
        '  "confianza_ia": "98%",\n'
        '  "datos_tecnicos": ["PR: [Valor] (Normal: 120-200 ms)"],\n'
        '  "lista_hallazgos": ["[Hallazgo real 1]", "[Hallazgo real 2]"],\n'
        '  "riesgo_quirurgico": "[Nivel] (Clase [X])",\n'
        '  "etiologia": "...",\n'
        '  "k_estimado": "[Valor]",\n'
        '  "ca_estimado": "[Valor]",\n'
        '  "manejo_sac": [\n'
        '    "1. [Estudio o derivación de urgencia] - ([Justificación])",\n'
        '    "2. [Fármaco] [Dosis] - ([Justificación])"\n'
        '  ],\n'
        '  "tecnicas_utilizadas": [\n'
        '    "1. Criterios de Sokolow-Lyon: Positivos (SV1 + RV5 > 35 mm, indicativo de HVI)",\n'
        '    "2. Criterios de Sgarbossa: Negativos (ausencia de elevación concordante del ST)"\n'
        '  ],\n'
        '  "marcas": [\n'
        '    {"x_porcentaje": 45.2, "y_porcentaje": 50.1, "nivel_riesgo": "alto", "descripcion_breve": "[Hallazgo real 1]", "id_espejo": null}\n'
        '  ]\n'
        "}"
    )

    modelos_autorizados = ['gemini-2.0-flash', 'gemini-1.5-flash-latest', 'gemini-1.5-flash']
    try:
        mods = [m.name.replace('models/', '') for m in client.models.list() if 'flash' in m.name.lower()]
        if mods: modelos_autorizados = mods
    except: pass

    analisis_hallazgos = None
    for modelo in modelos_autorizados:
        try:
            response = client.models.generate_content(
                model=modelo,
                contents=[ecg_orig, prompt_maestro],
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
            )
            texto_limpio = response.text.replace("```json", "").replace("
