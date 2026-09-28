import io
import os
import base64
import json
import time
import textwrap
from flask import Flask, request, send_file
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 60 * 1024 * 1024

api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
client = genai.Client(api_key=api_key) if api_key else genai.Client()

@app.route("/", methods=["GET"])
def home():
    return "API de Procesamiento de ECG Activa - Nivel Especialista (Cadena Única)"

@app.route("/analizar", methods=["POST"])
def analizar_ecg():
    # 1. ATRAPAR LA CADENA ÚNICA ENVIADA DESDE APP INVENTOR
    datos_paciente = request.args.get('datos', 'Paciente sin datos clínicos proporcionados.')
    
    # 2. PROCESAR LA IMAGEN
    ecg_orig = None
    data_cruda = request.get_data()
    try:
        if data_cruda:
            ecg_orig = Image.open(io.BytesIO(data_cruda)).convert("RGB")
    except Exception:
        pass

    if not ecg_orig:
        try:
            data = request.get_json(silent=True, force=True)
            imagen_base64 = data.get("image") or data.get("Image") if isinstance(data, dict) else None
            if not imagen_base64:
                cuerpo_crudo = data_cruda.decode("utf-8", errors="ignore").strip()
                imagen_base64 = cuerpo_crudo.replace('{"image":"', '').replace('{"Image":"', '').replace('image=', '').rstrip('"}').strip()
            image_data = base64.b64decode(imagen_base64)
            ecg_orig = Image.open(io.BytesIO(image_data)).convert("RGB")
        except Exception:
            try:
                if b"," in image_data:
                    image_data = image_data.split(b",", 1)[1]
                    ecg_orig = Image.open(io.BytesIO(image_data)).convert("RGB")
            except Exception as e:
                return {"error": f"Error al procesar imagen: {str(e)}"}, 400

    if not ecg_orig:
        return {"error": "No se recibió ninguna imagen válida."}, 400

    w_orig, h_orig = ecg_orig.size

    # 3. INYECTAR LA CADENA ÚNICA EN EL PROMPT MAESTRO
    prompt_maestro = (
        f"Actúa como el Mejor Cardiólogo Especialista del Mundo. Analiza minuciosamente esta imagen. "
        f"HISTORIA CLÍNICA DEL PACIENTE: {datos_paciente}. "
        "REGLA DE ORO INICIAL: Determina si la imagen contiene AL MENOS una línea de derivación de un electrocardiograma. "
        "Si NO es un ECG, establece 'es_ecg' en false y deja el resto vacío. "
        "Si ES un ECG, establece 'es_ecg' en true y sigue estas REGLAS CLÍNICAS MAESTRAS: "
        "1. ERROR DE ENFERMERÍA (CABLES): Verifica obligatoriamente si hay inversión de electrodos. Si detectas cables mal puestos, establece 'cables_invertidos' en true, y NO diagnostiques nada más. "
        "2. ASESINOS SILENCIOSOS: Descarta activamente la presencia de Síndrome de Wellens, Patrón de Brugada, Ondas T de De Winter, y aplica Criterios de Sgarbossa si hay Bloqueo de Rama Izquierda. "
        "3. MEDICIONES CUANTITATIVAS: Calcula estrictamente el Intervalo QTc y el Eje Eléctrico exacto en grados, inclúyelos en 'datos_tecnicos'. "
        "4. CONFIANZA: Asigna un porcentaje de calidad diagnóstica en 'confianza_ia'. "
        "Devuelve SOLO un JSON válido con estas claves exactas: "
        "'es_ecg' (boolean), "
        "'cables_invertidos' (boolean), "
        "'confianza_ia' (string), "
        "'datos_tecnicos' (array strings), "
        "'lista_hallazgos' (array), 'riesgo_quirurgico' (string), "
        "'etiologia' (string), 'k_estimado' (string), 'ca_estimado' (string), "
        "'manejo_sac' (string: detalla fármacos y dosis exactas según guías SAC/SAE), "
        "'marcas' (array de objetos: x_porcentaje, y_porcentaje, descripcion_breve, nivel_riesgo). "
        "REGLAS DE MARCAS: Correlación 1 a 1 de hallazgos. Marca TODAS las derivaciones afectadas, UNA sola marca por derivación. Coordenadas calculadas visualmente sobre ESTA foto. Riesgo: 'critico', 'alto', 'moderado', 'bajo', 'indeterminado'."
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
            analisis_hallazgos = json.loads(response.text.replace("```json", "").replace("
