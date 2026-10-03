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
    return "API de Procesamiento de ECG Activa - Versión Clínica Definitiva"

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

    # PROMPT MAESTRO DEFINITIVO (Informe técnico puro, sin debates literarios, con derivaciones en leyenda)
    prompt_maestro = (
        "INSTRUCCIÓN SUPREMA: Eres el Cardiólogo N°1 del Mundo. Analiza este ECG con rigor científico absoluto, onda por onda, con memoria fotográfica de todos los manuales de cardiología.\n"
        f"DATOS CLÍNICOS DEL PACIENTE: {datos_crudos}\n\n"
        "REGLAS INQUEBRANTABLES:\n"
        "1. CERO ALUCINACIONES: Diagnostica ÚNICAMENTE lo que ves. PROHIBIDO inventar bloqueos o patologías.\n"
        "2. CRITERIOS Y METODOLOGÍA PROFESIONAL ('tecnicas_utilizadas'): Lista de forma directa, técnica y profesional los criterios cardiológicos evaluados (ej. Wellens, Sgarbossa, Brugada, Sokolow-Lyon, Cornell, Cabrera, etc.). Indica si son POSITIVOS o NEGATIVOS y la justificación clínica breve. PROHIBIDO escribir diálogos o mencionar asistentes. Solo el informe médico técnico duro.\n"
        "3. ETIOLOGÍA CRÍTICAMENTE FUNDADA: Búsqueda etiológica profunda basada en la clínica y el trazado, evaluando diferenciales.\n"
        "4. TRATAMIENTO Y CONDUCTA SAC ('manejo_sac'): Orden jerárquico. 1° Estudios complementarios/urgencia, 2° Fármacos. CADA FÁRMACO LLEVA: Fármaco + Dosis exacta + (Justificación clínica entre paréntesis).\n"
        "5. SINCRONIZACIÓN DE MARCAS Y LEYENDA ('marcas'): Todo hallazgo que se salga del ritmo sinusal normal DEBE marcarse en TODAS las derivaciones afectadas. En 'descripcion_breve' INCLUYE SIEMPRE LA DERIVACIÓN Y EL HALLAZGO EXACTO (Ej: 'aVL - Onda Q patológica' o 'V1 - Infradesnivel ST').\n"
        "6. PRECISIÓN ESPACIAL: Las coordenadas (x, y) DEBEN posarse exactamente sobre la tinta del latido anómalo en la cuadrícula, jamás sobre el texto impreso.\n"
        "7. ESPEJOS ANATÓMICOS: Si hay lesión recíproca, asigna el mismo número entero en 'id_espejo' (ej. 1) a las marcas recíprocas para unirlas con líneas.\n"
        "8. CONFIANZA: 'confianza_ia' en porcentaje entero (ej: '99%').\n\n"
        "DEVUELVE EXCLUSIVAMENTE UN JSON VÁLIDO CON ESTA ESTRUCTURA:\n"
        "{\n"
        '  "es_ecg": true,\n'
        '  "cables_invertidos": false,\n'
        '  "anamnesis_redactada": "...",\n'
        '  "confianza_ia": "99%",\n'
        '  "datos_tecnicos": ["PR: [Valor] (Normal: 120-200 ms)"],\n'
        '  "lista_hallazgos": ["[Hallazgo real 1]", "[Hallazgo real 2]"],\n'
        '  "riesgo_quirurgico": "[Nivel] (Clase [X])",\n'
        '  "etiologia": "...",\n'
        '  "k_estimado": "[Valor]",\n'
        '  "ca_estimado": "[Valor]",\n'
        '  "manejo_sac": [\n'
        '    "1. [Estudio/Urgencia] - ([Justificación])",\n'
        '    "2. [Fármaco] [Dosis] - ([Justificación])"\n'
        '  ],\n'
        '  "tecnicas_utilizadas": [\n'
        '    "1. Criterios de Sokolow-Lyon: Positivos (SV1 + RV5 > 35 mm, indicativo de HVI).",\n'
        '    "2. Criterios de Sgarbossa: Negativos (ausencia de elevación concordante del ST)."\n'
        '  ],\n'
        '  "marcas": [\n'
        '    {"x_porcentaje": 45.2, "y_porcentaje": 50.1, "nivel_riesgo": "alto", "descripcion_breve": "aVL - Patrón qR (HBAI)", "id_espejo": null}\n'
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
            texto_limpio = response.text.replace("```json", "").replace("```", "").strip()
            analisis_hallazgos = json.loads(texto_limpio)
            if isinstance(analisis_hallazgos, dict):
                break
        except Exception:
            time.sleep(1)

    if not isinstance(analisis_hallazgos, dict):
        return {"error": "IA falló en todos los modelos o formato inválido."}, 500

    try:
        escala = max(1.2, w_orig / 1000.0)
        
        # PANTALLA DE ERROR: ECG INVÁLIDO CON EL PERRITO
        if not analisis_hallazgos.get("es_ecg", True):
            ancho_dog = int(max(800, w_orig))
            alto_dog = int(max(600, h_orig))
            img_perro = Image.new("RGB", (ancho_dog, alto_dog), color=(255, 255, 255))
            draw_dog = ImageDraw.Draw(img_perro)
            f_tit = cargar_fuente(28 * escala, negrita=True)
            draw_dog.text((ancho_dog//2 - int(250*escala), alto_dog//2), "🐶 NO SE DETECTAN DERIVACIONES. REPITA EL ECG.", fill=(180, 40, 40), font=f_tit)
            buf = io.BytesIO()
            img_perro.save(buf, format="PNG")
            buf.seek(0)
            return send_file(buf, mimetype="image/png")

        ancho_panel = int(950 * escala)
        col_w = int(38)  
        
        anamnesis_texto = str(analisis_hallazgos.get("anamnesis_redactada", datos_crudos))
        anamnesis_lines = [anamnesis_texto]

        datos_t_raw = analisis_hallazgos.get("datos_tecnicos", [])
        if isinstance(datos_t_raw, dict): datos_t_bruto = [f"{k}: {v}" for k, v in datos_t_raw.items()]
        elif isinstance(datos_t_raw, list): datos_t_bruto = [str(x) for x in datos_t_raw]
        else: datos_t_bruto = [str(datos_t_raw)]
        
        datos_t = []
        for d in datos_t_bruto:
            texto_d = str(d)
            if "Sin alteraciones" in texto_d or "sin alteraciones" in texto_d.lower():
                partes = texto_d.split("-")
                if len(partes) > 1:
                    texto_d = partes[0].strip()
            datos_t.append(texto_d)
            
        lista_h = analisis_hallazgos.get("lista_hallazgos", [])
        if not isinstance(lista_h, list): lista_h = [str(lista_h)]
        lista_h.append(f"RIESGO QUIRÚRGICO: {analisis_hallazgos.get('riesgo_quirurgico', 'No evaluado')}")
        etiologia = [str(analisis_hallazgos.get("etiologia", "N/A"))]
        
        manejo_raw = analisis_hallazgos.get("manejo_sac", ["Se requieren más datos para pauta farmacológica."])
        if isinstance(manejo_raw, str):
            manejo = manejo_raw.split('\n')
        elif isinstance(manejo_raw, list):
            manejo = [str(x) for x in manejo_raw]
        else:
            manejo = [str(manejo_raw)]
        
        tecnicas = analisis_hallazgos.get("tecnicas_utilizadas", [])
        if not isinstance(tecnicas, list): tecnicas = [str(tecnicas)]
        
        conf_val = analisis_hallazgos.get('confianza_ia', 'N/A')
        if isinstance(conf_val, (float, int)):
            if conf_val <= 1:
                conf_val = f"{int(conf_val * 100)}%"
            else:
                conf_val = f"{conf_val}%"
        tecnicas.insert(0, f"CONFIANZA DEL ANÁLISIS IA: {conf_val}")

        marcas_crudas = analisis_hallazgos.get("marcas", [])
        if isinstance(marcas_crudas, dict): 
            marcas_crudas = [marcas_crudas]
        elif not isinstance(marcas_crudas, list): 
            marcas_crudas = []
            
        marcas_ia = []
        for m in marcas_crudas:
            if isinstance(m, dict):
                marcas_ia.append(m)
        
        colores_riesgo = {
            'critico': ((220, 30, 30, 140), 'Riesgo Crítico'),
            'alto': ((148, 0, 211, 140), 'Riesgo Alto'),
            'moderado': ((220, 200, 30, 140), 'Riesgo Moderado'),
            'bajo': ((30, 200, 30, 140), 'Riesgo Bajo'),
            'indeterminado': ((30, 100, 220, 140), 'A Confirmar')
        }

        orden_jerarquia = ['critico', 'alto', 'moderado', 'bajo', 'indeterminado']
        tipos_presentes = {}
        
        for m in marcas_ia:
            r = obtener_riesgo_real(m.get("nivel_riesgo", "indeterminado"))
            desc = str(m.get("descripcion_breve", "Alteración")).strip()
            if r not in tipos_presentes: tipos_presentes[r] = []
            if desc and desc not in tipos_presentes[r]: tipos_presentes[r].append(desc)

        def calc_y(lineas):
            h = 20 * escala
            for item in lineas: h += len(textwrap.wrap(f"• {item}", width=col_w)) * (18 * escala)
            return h + (25 * escala)

        h_c1 = (45*escala) + calc_y(anamnesis_lines) + calc_y(datos_t) + calc_y([f"K+: {analisis_hallazgos.get('k_estimado', '')}", f"Ca2+: {analisis_hallazgos.get('ca_estimado', '')}"]) + (len(tipos_presentes) * 75 * escala) + (60*escala)
        h_c2 = (45*escala) + calc_y(lista_h) + calc_y(etiologia)
        h_c3 = (45*escala) + calc_y(tecnicas) + calc_y(manejo) + (40*escala)

        alto_final = int(max(h_orig, h_c1, h_c2, h_c3))
        
        img_final = Image.new("RGB", (w_orig + ancho_panel, alto_final), color=(248, 248, 250))
        img_final.paste(ecg_orig, (0, 0))
        c_overlay = Image.new("RGBA", img_final.size, (255, 255, 255, 0))
        draw_ov = ImageDraw.Draw(c_overlay)
        draw_final = ImageDraw.Draw(img_final)

        f_titulo = cargar_fuente(18 * escala, negrita=True)
        f_sub = cargar_fuente(14 * escala, negrita=True)
        f_texto = cargar_fuente(13 * escala, negrita=False)

        # BANDA ROJA DE ALERTA CLÍNICA (Se activa si hay riesgo alto o crítico)
        hay_riesgo_alto = any(r in tipos_presentes for r in ['critico', 'alto'])
        if hay_riesgo_alto:
            draw_final.rectangle([w_orig, 0, w_orig + ancho_panel, int(35 * escala)], fill=(200, 40, 40))
            draw_final.text((w_orig + int(20 * escala), int(8 * escala)), "⚠️ ALERTA CLÍNICA: RIESGO CARDIOVASCULAR ELEVADO DETECTADO", fill=(255, 255, 255), font=f_titulo)
            margen_y_titulos = int(55 * escala)
        else:
            draw_final.text((w_orig + int(20 * escala), int(15 * escala)), "RESEÑA CARDIOLÓGICA PROFUNDA Y MANEJO CLÍNICO", fill=(20, 50, 100), font=f_titulo)
            draw_final.line([(w_orig + int(20 * escala), int(40 * escala)), (w_orig + ancho_panel - int(20 * escala), int(40 * escala))], fill=(220, 220, 220), width=int(max(1, escala)))
            margen_y_titulos = int(55 * escala)

        c1_x = int(w_orig + (20 * escala))
        c2_x = int(w_orig + (330 * escala))
        c3_x = int(w_orig + (640 * escala))
        
        draw_final.line([(w_orig, 0), (w_orig, alto_final)], fill=(200, 200, 200), width=int(max(1, escala)))

        def render_txt(x, y, titulo, lineas):
            draw_final.text((x, y), titulo, fill=(40, 80, 140), font=f_sub)
            y += int(25 * escala)
            for item in lineas:
                for p in textwrap.wrap(f"• {item}", width=col_w):
                    draw_final.text((x, y), p, fill=(45, 45, 45), font=f_texto)
                    y += int(18 * escala)
            return y + int(25 * escala)

        y_c1 = render_txt(c1_x, margen_y_titulos, "ANAMNESIS DEL PACIENTE:", anamnesis_lines)
        y_c1 = render_txt(c1_x, y_c1, "ANÁLISIS DE ONDAS Y SEGMENTOS:", datos_t)
        y_c1 = render_txt(c1_x, y_c1, "IONOGRAMA ESTIMADO:", [f"K+: {analisis_hallazgos.get('k_estimado', '')}", f"Ca2+: {analisis_hallazgos.get('ca_estimado', '')}"])
        
        if tipos_presentes:
            draw_final.text((c1_x, y_c1), "LEYENDA DE COLORES (Por Riesgo):", fill=(40, 80, 140), font=f_sub)
            y_c1 += int(25 * escala)
            for r in orden_jerarquia:
                if r in tipos_presentes:
                    desc_list = tipos_presentes[r]
                    rgba, desc_base = colores_riesgo[r]
                    txt_leyenda = f"{desc_base}: {', '.join(desc_list)}" if desc_list else desc_base
                    r_size = int(12 * escala)
                    color_leyenda = (rgba[0], rgba[1], rgba[2], 255)
                    draw_ov.ellipse([c1_x, y_c1+int(2*escala), c1_x+r_size, y_c1+r_size+int(2*escala)], fill=color_leyenda)
                    for p in textwrap.wrap(txt_leyenda, width=col_w - 2):
                        draw_final.text((c1_x + int(25 * escala), y_c1), p, fill=(45, 45, 45), font=f_texto)
                        y_c1 += int(18 * escala)
                    y_c1 += int(15 * escala)

        y_c2 = render_txt(c2_x, margen_y_titulos, "HALLAZGOS CLAVE:", lista_h)
        y_c2 = render_txt(c2_x, y_c2, "ETIOLOGÍA (Diferenciales):", etiologia)
        y_c3 = render_txt(c3_x, margen_y_titulos, "METODOLOGÍA Y RAZONAMIENTO IA:", tecnicas)
        y_c3 = render_txt(c3_x, y_c3, "TRATAMIENTO Y CONDUCTA (SAC):", manejo)

        puntos_espejo = {}

        for m in marcas_ia:
            try:
                r = obtener_riesgo_real(m.get("nivel_riesgo", "indeterminado"))
                
                val_x = safe_float(m.get("x_porcentaje", 50))
                val_y = safe_float(m.get("y_porcentaje", 50))
                
                ia_x = int(w_orig * (max(0.0, min(100.0, val_x)) / 100.0))
                ia_y = int(h_orig * (max(0.0, min(100.0, val_y)) / 100.0))
                
                px, py = snap_to_ecg_trace_smart(ecg_orig, ia_x, ia_y, w_orig, h_orig)
                
                rad = int(14 * escala)
                draw_ov.ellipse([px-rad, py-rad, px+rad, py+rad], fill=colores_riesgo[r][0])

                id_e = m.get("id_espejo")
                if id_e is not None and str(id_e).strip().lower() not in ["", "null", "none"]:
                    if id_e not in puntos_espejo:
                        puntos_espejo[id_e] = []
                    puntos_espejo[id_e].append( ((px, py), colores_riesgo[r][0]) )
            except Exception:
                continue

        # FLECHAS NEGRAS FINAS PARA UNIR ESPEJOS
        for id_e, puntos in puntos_espejo.items():
            if len(puntos) == 2: 
                origen, color_origen = puntos[0]
                destino, color_destino = puntos[1]
                color_linea = (20, 20, 20, 230)
                draw_dotted_arrow(draw_ov, origen, destino, color_linea, escala)

        img_final = Image.alpha_composite(img_final.convert("RGBA"), c_overlay).convert("RGB")
        buf = io.BytesIO()
        img_final.save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")

    except Exception as e:
        return {"error": f"Error render: {str(e)}"}, 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
