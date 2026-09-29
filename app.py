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

def obtener_riesgo_real(texto_riesgo):
    v = str(texto_riesgo).lower()
    if 'cr' in v: return 'critico'
    if 'alt' in v: return 'alto'
    if 'mod' in v: return 'moderado'
    if 'baj' in v: return 'bajo'
    return 'indeterminado'

@app.route("/", methods=["GET"])
def home():
    return "API de Procesamiento de ECG Activa - ST Recíproco, Marcas Múltiples y Leyenda Ordenada"

@app.route("/analizar", methods=["POST"])
def analizar_ecg():
    datos_crudos = request.args.get('datos', 'Paciente sin datos clínicos proporcionados.')
    
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

    prompt_maestro = (
        f"Actúa como el Mejor Cardiólogo Especialista del Mundo. Analiza minuciosamente esta imagen. "
        f"DATOS CLÍNICOS BRUTOS INGRESADOS: {datos_crudos}. "
        "REGLA DE ORO INICIAL: Determina si la imagen contiene AL MENOS una línea de derivación de un electrocardiograma. "
        "Si NO es un ECG, establece 'es_ecg' en false y deja el resto vacío. "
        "Si ES un ECG, establece 'es_ecg' in true y sigue estas REGLAS CLÍNICAS MAESTRAS: "
        "1. ANAMNESIS PROFESIONAL: Toma los 'DATOS CLÍNICOS BRUTOS' provistos y reescríbelos en 'anamnesis_redactada'. "
        "2. ANÁLISIS DE ISQUEMIA Y ST (CAMBIOS RECÍPROCOS): Al evaluar el segmento ST, estás OBLIGADO a buscar imágenes en espejo (cambios recíprocos) en derivaciones opuestas. Analiza todas las derivaciones en conjunto para confirmar lesión subepicárdica o isquemia. Documenta esto explícitamente. "
        "3. ASESINOS SILENCIOSOS Y MÉTRICAS: Calcula Frecuencia Cardíaca, Ritmo, Eje Eléctrico y QTc. Evalúa Sgarbossa, Wellens, Brugada, De Winter. "
        "4. ANÁLISIS CONDICIONAL: En 'datos_tecnicos', si el parámetro ES NORMAL, escribe únicamente el valor y su rango normal. SOLO si ESTÁ ALTERADO, agrega la posible causa clínica. "
        "5. CONFIANZA: Asigna un porcentaje en 'confianza_ia'. "
        "Devuelve SOLO un JSON válido con estas claves exactas: "
        "'es_ecg' (boolean), 'cables_invertidos' (boolean), 'anamnesis_redactada' (string), 'confianza_ia' (string), "
        "'datos_tecnicos' (array strings), 'lista_hallazgos' (array), 'riesgo_quirurgico' (string), "
        "'etiologia' (string), 'k_estimado' (string), 'ca_estimado' (string), 'manejo_sac' (string), "
        "'tecnicas_utilizadas' (array strings), "
        "'marcas' (array de objetos: x_porcentaje, y_porcentaje, descripcion_breve, nivel_riesgo). "
        "REGLAS ESTRICTAS DE MARCAS Y COORDENADAS (CRÍTICO): "
        "A) EXHAUSTIVIDAD MULTICOLOR: Genera MÚLTIPLES marcas. Debes crear un objeto en el array por CADA derivación alterada. Asigna 'critico' (Rojo) a supradesniveles ST/infartos, 'alto' (Violeta) a infradesniveles ST/isquemia grave/arritmias, 'moderado' (Amarillo) a bloqueos/hipertrofias, y 'bajo' (Verde) a hallazgos leves. "
        "B) UBICACIÓN EXACTA: 'x_porcentaje' es el eje horizontal (0=izquierda absoluta, 100=derecha absoluta). 'y_porcentaje' es el eje vertical (0=arriba, 100=abajo). Apunta al latido más representativo de cada derivación afectada, cayendo EXACTAMENTE sobre la tinta negra de la anomalía."
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
            analisis_hallazgos = json.loads(response.text.replace("```json", "").replace("```", "").strip())
            break
        except Exception:
            time.sleep(1)

    if not analisis_hallazgos:
        return {"error": "IA falló en todos los modelos."}, 500

    try:
        escala = max(1.0, w_orig / 1200.0)
        
        if not analisis_hallazgos.get("es_ecg", True):
            ancho_dog = int(max(800, w_orig))
            alto_dog = int(max(600, h_orig))
            img_perro = Image.new("RGB", (ancho_dog, alto_dog), color=(255, 255, 255))
            draw_dog = ImageDraw.Draw(img_perro)
            cx, cy = ancho_dog // 2, alto_dog // 2
            grosor = int(5 * escala)
            
            draw_dog.ellipse([cx-120*escala, cy-120*escala, cx+120*escala, cy+120*escala], outline=(40,40,40), width=grosor) 
            draw_dog.ellipse([cx-160*escala, cy-90*escala, cx-80*escala, cy+70*escala], outline=(40,40,40), width=grosor)  
            draw_dog.ellipse([cx+80*escala, cy-90*escala, cx+160*escala, cy+70*escala], outline=(40,40,40), width=grosor)   
            draw_dog.ellipse([cx-50*escala, cy-30*escala, cx-25*escala, cy-5*escala], fill=(40,40,40))                     
            draw_dog.ellipse([cx+25*escala, cy-30*escala, cx+50*escala, cy-5*escala], fill=(40,40,40))                     
            draw_dog.ellipse([cx-15*escala, cy+15*escala, cx+15*escala, cy+35*escala], fill=(40,40,40))                    
            draw_dog.arc([cx-40*escala, cy+15*escala, cx, cy+55*escala], start=0, end=180, fill=(40,40,40), width=grosor)  
            draw_dog.arc([cx, cy+15*escala, cx+40*escala, cy+55*escala], start=0, end=180, fill=(40,40,40), width=grosor)  

            try: f_tit = ImageFont.truetype("DejaVuSans-Bold.ttf", int(30 * escala))
            except: f_tit = ImageFont.load_default()
            
            m1 = "¡Guau! Esto no parece un electrocardiograma."
            m2 = "Por favor, selecciona una imagen con derivaciones."
            draw_dog.text((cx - (len(m1)*8*escala), cy + 160*escala), m1, fill=(80, 80, 80), font=f_tit)
            draw_dog.text((cx - (len(m2)*8*escala), cy + 200*escala), m2, fill=(80, 80, 80), font=f_tit)

            buf = io.BytesIO()
            img_perro.save(buf, format="PNG", compress_level=0)
            buf.seek(0)
            return send_file(buf, mimetype="image/png")

        if analisis_hallazgos.get("cables_invertidos", False):
            ancho_silueta = int(max(900, w_orig))
            alto_silueta = int(max(700, h_orig))
            img_sil = Image.new("RGB", (ancho_silueta, alto_silueta), color=(245, 245, 245))
            draw_sil = ImageDraw.Draw(img_sil)
            cx, cy = ancho_silueta // 2, alto_silueta // 2
            
            try:
                f_tit = ImageFont.truetype("DejaVuSans-Bold.ttf", int(24 * escala))
                f_txt = ImageFont.truetype("DejaVuSans.ttf", int(16 * escala))
                f_chico = ImageFont.truetype("DejaVuSans-Bold.ttf", int(12 * escala))
            except:
                f_tit = f_txt = f_chico = ImageFont.load_default()

            draw_sil.text((cx - (250*escala), 40*escala), "ALERTA: ELECTRODOS INVERTIDOS", fill=(200, 30, 30), font=f_tit)
            draw_sil.text((cx - (300*escala), 80*escala), "Se detectó inversión de cables (Ej. aVR positivo). Por favor, repita el ECG usando esta guía:", fill=(50, 50, 50), font=f_txt)

            g = int(4 * escala)
            color_cuerpo = (180, 180, 180)
            draw_sil.ellipse([cx-40*escala, cy-200*escala, cx+40*escala, cy-120*escala], outline=color_cuerpo, width=g) 
            draw_sil.line([cx, cy-120*escala, cx, cy-90*escala], fill=color_cuerpo, width=g) 
            draw_sil.line([cx-140*escala, cy-90*escala, cx+140*escala, cy-90*escala], fill=color_cuerpo, width=g) 
            draw_sil.line([cx-140*escala, cy-90*escala, cx-160*escala, cy+40*escala], fill=color_cuerpo, width=g) 
            draw_sil.line([cx+140*escala, cy-90*escala, cx+160*escala, cy+40*escala], fill=color_cuerpo, width=g) 
            draw_sil.line([cx-80*escala, cy-90*escala, cx-80*escala, cy+100*escala], fill=color_cuerpo, width=g) 
            draw_sil.line([cx+80*escala, cy-90*escala, cx+80*escala, cy+100*escala], fill=color_cuerpo, width=g) 
            draw_sil.line([cx-80*escala, cy+100*escala, cx+80*escala, cy+100*escala], fill=color_cuerpo, width=g) 
            draw_sil.line([cx-60*escala, cy+100*escala, cx-60*escala, cy+250*escala], fill=color_cuerpo, width=g) 
            draw_sil.line([cx+60*escala, cy+100*escala, cx+60*escala, cy+250*escala], fill=color_cuerpo, width=g) 

            def poner_electrodo(x, y, nombre, color_pin):
                r = int(10*escala)
                draw_sil.ellipse([x-r, y-r, x+r, y+r], fill=color_pin)
                draw_sil.text((x + 15*escala, y - 8*escala), nombre, fill=(40,40,40), font=f_chico)

            poner_electrodo(cx-160*escala, cy-20*escala, "RA (Rojo)", (200,40,40))
            poner_electrodo(cx+160*escala, cy-20*escala, "LA (Amarillo)", (200,200,40))
            poner_electrodo(cx-60*escala, cy+220*escala, "RL (Negro)", (40,40,40))
            poner_electrodo(cx+60*escala, cy+220*escala, "LL (Verde)", (40,200,40))

            buf = io.BytesIO()
            img_sil.save(buf, format="PNG", compress_level=0)
            buf.seek(0)
            return send_file(buf, mimetype="image/png")

        ancho_panel = int(920 * escala)
        col_w = int(42)
        
        anamnesis_texto = str(analisis_hallazgos.get("anamnesis_redactada", datos_crudos))
        anamnesis_lines = [anamnesis_texto]

        dt = analisis_hallazgos.get("datos_tecnicos", [])
        datos_t = [str(x) for x in dt] if isinstance(dt, list) else [str(dt)]
        
        lista_h = analisis_hallazgos.get("lista_hallazgos", [])
        if not isinstance(lista_h, list): lista_h = [str(lista_h)]
        lista_h.append(f"RIESGO QUIRÚRGICO: {analisis_hallazgos.get('riesgo_quirurgico', 'No evaluado')}")
        etiologia = [str(analisis_hallazgos.get("etiologia", "N/A"))]
        
        manejo = str(analisis_hallazgos.get("manejo_sac", "N/A")).split('\n')
        
        tecnicas = analisis_hallazgos.get("tecnicas_utilizadas", [])
        if not isinstance(tecnicas, list): tecnicas = [str(tecnicas)]
        confianza = analisis_hallazgos.get("confianza_ia", "N/A")
        tecnicas.insert(0, f"CONFIANZA DEL ANÁLISIS VISUAL: {confianza}")

        marcas_ia = analisis_hallazgos.get("marcas", [])
        
        colores_riesgo = {
            'critico': ((220, 30, 30, 200), 'Riesgo Crítico'),
            'alto': ((148, 0, 211, 200), 'Riesgo Alto'),
            'moderado': ((220, 200, 30, 200), 'Riesgo Moderado'),
            'bajo': ((30, 200, 30, 200), 'Riesgo Bajo'),
            'indeterminado': ((30, 100, 220, 200), 'A Confirmar / Artefacto')
        }

        # Jerarquía estricta para ordenar la leyenda de colores
        orden_jerarquia = ['critico', 'alto', 'moderado', 'bajo', 'indeterminado']
        tipos_presentes_crudos = {}
        
        for m in marcas_ia:
            r = obtener_riesgo_real(m.get("nivel_riesgo", "indeterminado"))
            desc = str(m.get("descripcion_breve", "Alteración")).strip()
            
            if r not in tipos_presentes_crudos: tipos_presentes_crudos[r] = []
            if desc and desc not in tipos_presentes_crudos[r]: tipos_presentes_crudos[r].append(desc)

        def calc_y(lineas):
            h = 20 * escala
            for item in lineas: h += len(textwrap.wrap(f"• {item}", width=col_w)) * (16 * escala)
            return h + (20 * escala)

        h_c1 = (45*escala) + calc_y(anamnesis_lines) + calc_y(datos_t) + calc_y([f"K+: {analisis_hallazgos.get('k_estimado', '')}", f"Ca2+: {analisis_hallazgos.get('ca_estimado', '')}"]) + (len(tipos_presentes_crudos) * 60 * escala) + (40*escala)
        h_c2 = (45*escala) + calc_y(lista_h) + calc_y(etiologia)
        h_c3 = (45*escala) + calc_y(manejo) + calc_y(tecnicas)

        alto_final = int(max(h_orig, h_c1, h_c2, h_c3))
        
        img_final = Image.new("RGB", (w_orig + ancho_panel, alto_final), color=(248, 248, 250))
        img_final.paste(ecg_orig, (0, 0))
        c_overlay = Image.new("RGBA", img_final.size, (255, 255, 255, 0))
        draw_ov = ImageDraw.Draw(c_overlay)
        draw = ImageDraw.Draw(img_final)

        try:
            f_titulo = ImageFont.truetype("DejaVuSans-Bold.ttf", int(16 * escala))
            f_sub = ImageFont.truetype("DejaVuSans-Bold.ttf", int(12 * escala))
            f_texto = ImageFont.truetype("DejaVuSans.ttf", int(11 * escala))
        except:
            f_titulo = f_sub = f_texto = ImageFont.load_default()

        c1_x = int(w_orig + (15 * escala))
        c2_x = int(w_orig + (315 * escala))
        c3_x = int(w_orig + (615 * escala))
        
        draw.line([(w_orig, 0), (w_orig, alto_final)], fill=(200, 200, 200), width=int(max(1, escala)))
        draw.text((c1_x, int(15 * escala)), "RESEÑA CARDIOLÓGICA PROFUNDA Y MANEJO CLÍNICO", fill=(20, 50, 100), font=f_titulo)
        draw.line([(c1_x, int(35 * escala)), (w_orig + ancho_panel - int(15 * escala), int(35 * escala))], fill=(220, 220, 220), width=int(max(1, escala)))

        def render_txt(x, y, titulo, lineas):
            draw.text((x, y), titulo, fill=(40, 80, 140), font=f_sub)
            y += int(20 * escala)
            for item in lineas:
                for p in textwrap.wrap(f"• {item}", width=col_w):
                    draw.text((x, y), p, fill=(50, 50, 50), font=f_texto)
                    y += int(16 * escala)
            return y + int(20 * escala)

        y_c1 = render_txt(c1_x, int(45 * escala), "ANAMNESIS DEL PACIENTE:", anamnesis_lines)
        y_c1 = render_txt(c1_x, y_c1, "ANÁLISIS DE ONDAS Y SEGMENTOS:", datos_t)
        y_c1 = render_txt(c1_x, y_c1, "IONOGRAMA ESTIMADO:", [f"K+: {analisis_hallazgos.get('k_estimado', '')}", f"Ca2+: {analisis_hallazgos.get('ca_estimado', '')}"])
        
        # Renderizado de leyenda con orden jerárquico forzado
        if tipos_presentes_crudos:
            draw.text((c1_x, y_c1), "LEYENDA DE COLORES (Por Riesgo):", fill=(40, 80, 140), font=f_sub)
            y_c1 += int(20 * escala)
            
            for r in orden_jerarquia:
                if r in tipos_presentes_crudos:
                    desc_list = tipos_presentes_crudos[r]
                    rgba, desc_base = colores_riesgo[r]
                    txt_leyenda = f"{desc_base}: {', '.join(desc_list)}" if desc_list else desc_base
                    
                    r_size = int(10 * escala)
                    draw_ov.ellipse([c1_x, y_c1+int(2*escala), c1_x+r_size, y_c1+r_size+int(2*escala)], fill=rgba)
                    
                    for p in textwrap.wrap(txt_leyenda, width=col_w - 2):
                        draw.text((c1_x + int(22 * escala), y_c1), p, fill=(50, 50, 50), font=f_texto)
                        y_c1 += int(16 * escala)
                    y_c1 += int(12 * escala)

        y_c2 = render_txt(c2_x, int(45 * escala), "HALLAZGOS CLAVE:", lista_h)
        y_c2 = render_txt(c2_x, y_c2, "ETIOLOGÍA (Diferenciales):", etiologia)

        y_c3 = render_txt(c3_x, int(45 * escala), "MANEJO CLÍNICO (SAC/SAE):", manejo)
        y_c3 = render_txt(c3_x, y_c3, "TÉCNICAS DE ANÁLISIS IA:", tecnicas)

        for m in marcas_ia:
            try:
                r = obtener_riesgo_real(m.get("nivel_riesgo", "indeterminado"))
                
                raw_x = str(m.get("x_porcentaje", 50)).replace('%', '').strip()
                raw_y = str(m.get("y_porcentaje", 50)).replace('%', '').strip()
                x_val = float(raw_x)
                y_val = float(raw_y)
                
                px = int(w_orig * (max(0.0, min(100.0, x_val)) / 100.0))
                py = int(h_orig * (max(0.0, min(100.0, y_val)) / 100.0))
                
                rad = int(12 * escala)
                draw_ov.ellipse([px-rad, py-rad, px+rad, py+rad], fill=colores_riesgo[r][0])
            except Exception:
                continue

        img_final = Image.alpha_composite(img_final.convert("RGBA"), c_overlay).convert("RGB")
        buf = io.BytesIO()
        img_final.save(buf, format="PNG", compress_level=0)
        buf.seek(0)
        return send_file(buf, mimetype="image/png")

    except Exception as e:
        return {"error": f"Error render: {str(e)}"}, 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
