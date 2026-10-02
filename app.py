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

# ESCÁNER ORIGINAL INTACTO
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

def draw_dotted_arrow(draw, pt1, pt2, color, escala):
    x1, y1 = pt1
    x2, y2 = pt2
    dist = math.hypot(x2 - x1, y2 - y1)
    if dist < 15 * escala: return 
    
    angle = math.atan2(y2 - y1, x2 - x1)
    dash_length = 4 * escala
    width = max(1, int(1.5 * escala))
    
    d = 0
    while d < dist:
        end_d = min(d + dash_length, dist)
        start_x = x1 + math.cos(angle) * d
        start_y = y1 + math.sin(angle) * d
        end_x = x1 + math.cos(angle) * end_d
        end_y = y1 + math.sin(angle) * end_d
        draw.line([(start_x, start_y), (end_x, end_y)], fill=color, width=width)
        d += dash_length * 2.5
        
    head_len = 8 * escala
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
    return "API de Procesamiento de ECG Activa - Versión Mente Brillante"

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

    # PROMPT MAESTRO: IDENTIDAD DE MENTE BRILLANTE Y MEMORIA FOTOGRÁFICA
    prompt_maestro = (
        "ERES EL MEJOR CARDIÓLOGO DEL MUNDO, UNA MENTE BRILLANTE CON MEMORIA FOTOGRÁFICA DE TODAS LAS ALTERACIONES JAMÁS DESCRITAS EN LOS MANUALES DE CARDIOLOGÍA.\n"
        f"DATOS CLÍNICOS: {datos_crudos}\n\n"
        "REGLAS INQUEBRANTABLES:\n"
        "1. CONFIANZA: 'confianza_ia' DEBE ser un porcentaje entero (ej. '98%'). PROHIBIDO usar decimales.\n"
        "2. DATOS TÉCNICOS NORMALES: Si un parámetro es normal, escribe SOLO el valor. Ej: 'PR: 160 ms (Normal: 120-200 ms)'. ESTÁ ESTRICTAMENTE PROHIBIDO añadir texto de relleno como 'Sin alteraciones'.\n"
        "3. METODOLOGÍA (ENCICLOPEDIA VIVIENTE): Demuestra tu genialidad. Correlaciona minuciosamente TODAS las ondas en conjunto. TIENES QUE EVALUAR y nombrar la aplicación de los criterios de todos los próceres de la cardiología (Wellens, Sgarbossa, Brugada, Sokolow-Lyon, Cornell, Cabrera, de Winter, y absolutamente cualquier otro criterio o triada que exista en la literatura médica). PROHIBIDO poner pasos básicos.\n"
        "4. TRATAMIENTO FARMACOLÓGICO SAC ('manejo_sac'): Es OBLIGATORIO recetar fármacos específicos con sus DOSIS EXACTAS y posología según la SAC. PROHIBIDO poner solo el grupo terapéutico o el fármaco sin la dosis. Ej: 'Aspirina 100 mg/día'.\n"
        "5. LEYENDA CLARA: En 'descripcion_breve', pon la patología exacta (ej. 'Infradesnivel ST', 'Hemibloqueo'). PROHIBIDO usar la palabra 'Alteración'.\n"
        "6. RIESGO EN MARCAS: Usa SOLO 'critico', 'alto', 'moderado', o 'bajo'.\n"
        "7. EXHAUSTIVIDAD FORZADA: Con tu memoria fotográfica, identifica CADA anomalía y MÁRCALAS ABSOLUTAMENTE TODAS en las derivaciones correspondientes. Eres exhaustivo al 100%.\n"
        "8. PRECISIÓN ESPACIAL: Posiciona las coordenadas x_porcentaje e y_porcentaje EXACTAMENTE sobre la tinta del latido afectado en la cuadrícula.\n"
        "9. ESPEJOS ANATÓMICOS: Si detectas una lesión recíproca (ej. supra en cara inferior e infra en cara lateral), DEBES usar el mismo número en 'id_espejo' (ej. 1) en esas marcas para unirlas.\n\n"
        "DEVUELVE EXCLUSIVAMENTE UN JSON CON ESTA ESTRUCTURA EXACTA:\n"
        "{\n"
        '  "es_ecg": true,\n'
        '  "cables_invertidos": false,\n'
        '  "anamnesis_redactada": "...",\n'
        '  "confianza_ia": "98%",\n'
        '  "datos_tecnicos": [\n'
        '    "PR: 160 ms (Normal: 120-200 ms)",\n'
        '    "Eje: -45° (Desviado a la izq por HBAI)"\n'
        '  ],\n'
        '  "lista_hallazgos": ["Hemibloqueo anterior izquierdo", "Sobrecarga sistólica"],\n'
        '  "riesgo_quirurgico": "Riesgo Moderado (Clase II)",\n'
        '  "etiologia": "...",\n'
        '  "k_estimado": "4.0",\n'
        '  "ca_estimado": "9.5",\n'
        '  "manejo_sac": [\n'
        '    "1. Iniciar Ácido Acetilsalicílico (AAS) 100 mg/día vía oral.",\n'
        '    "2. Atorvastatina 40 mg/día vía oral.",\n'
        '    "3. Bisoprolol 2.5 mg/día (controlar FC)." \n'
        '  ],\n'
        '  "tecnicas_utilizadas": [\n'
        '    "1. Evaluación exhaustiva de Criterios de Sokolow-Lyon y Cornell.",\n'
        '    "2. Descartados patrones de Wellens, Brugada y equivalentes isquémicos de de Winter."\n'
        '  ],\n'
        '  "marcas": [\n'
        '    {"x_porcentaje": 45.2, "y_porcentaje": 30.1, "nivel_riesgo": "alto", "descripcion_breve": "Patrón qR (HBAI)", "id_espejo": 1},\n'
        '    {"x_porcentaje": 60.5, "y_porcentaje": 70.2, "nivel_riesgo": "alto", "descripcion_breve": "Cambios recíprocos", "id_espejo": 1}\n'
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
