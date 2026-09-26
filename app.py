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
    return "API de Procesamiento de ECG Activa."

@app.route("/analizar", methods=["POST"])
def analizar_ecg():
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
        "Actúa como un Cardiólogo Especialista Avanzado. Analiza minuciosamente este ECG. "
        "REGLAS CLÍNICAS CRÍTICAS: "
        "1. Ignora texto escrito a mano. Analiza solo derivaciones. "
        "2. Razona cruzando información de todas las derivaciones. "
        "3. Si dudas por interferencia, pon 'sospecha a confirmar'. "
        "4. Enumera diagnósticos diferenciales si corresponde. "
        "Devuelve SOLO un JSON válido. Claves exactas: "
        "'datos_tecnicos' (array strings), "
        "'lista_hallazgos' (array), 'riesgo_quirurgico' (string), "
        "'etiologia' (string), 'k_estimado' (string), 'ca_estimado' (string), "
        "'manejo_sac' (string: detalla fármacos y dosis según guías SAC/SAE), "
        "'marcas' (array de objetos: x_porcentaje, y_porcentaje, descripcion_breve, nivel_riesgo). "
        "REGLAS DE MARCAS (EXHAUSTIVIDAD OBLIGATORIA - NO OMITAS NADA): "
        "1. CORRELACIÓN 1 A 1: Cada anomalía mencionada en 'lista_hallazgos' DEBE tener OBLIGATORIAMENTE marcas en el array 'marcas'. No seas perezoso, marca todo lo que describas. "
        "2. REGLA DE UBICACIÓN (1 MARCA POR DERIVACIÓN): Si una alteración aparece en varias derivaciones (ej. infradesnivel en V2, V3 y V4), crea exactamente UNA marca en V2, UNA en V3 y UNA en V4. Selecciona un solo latido representativo por derivación. PROHIBIDO marcar todos los latidos de una misma derivación, márcalo solo 1 vez por derivación afectada. "
        "3. 'nivel_riesgo' DEBE ser exactamente: 'critico', 'alto', 'moderado', 'bajo', 'indeterminado'. "
        "4. Coordenadas (0-100) exactas sobre el trazo."
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
        ancho_panel = int(920 * escala)
        col_w = int(42)
        
        dt = analisis_hallazgos.get("datos_tecnicos", [])
        datos_t = [str(x) for x in dt] if isinstance(dt, list) else [str(dt)]
        lista_h = analisis_hallazgos.get("lista_hallazgos", [])
        if not isinstance(lista_h, list): lista_h = [str(lista_h)]
        lista_h.append(f"RIESGO QUIRÚRGICO: {analisis_hallazgos.get('riesgo_quirurgico', 'No evaluado')}")
        manejo = str(analisis_hallazgos.get("manejo_sac", "N/A")).split('\n')
        
        marcas_ia = analisis_hallazgos.get("marcas", [])
        
        # Mapeo de Colores por Severidad (Rojo, Morado, Amarillo, Verde, Azul)
        colores_riesgo = {
            'critico': ((220, 30, 30, 130), 'Riesgo Crítico'),
            'alto': ((148, 0, 211, 130), 'Riesgo Alto'),
            'moderado': ((220, 200, 30, 130), 'Riesgo Moderado'),
            'bajo': ((30, 200, 30, 130), 'Riesgo Bajo'),
            'indeterminado': ((30, 100, 220, 130), 'A Confirmar / Artefacto')
        }

        tipos_presentes = {}
        for m in marcas_ia:
            r = str(m.get("nivel_riesgo", "indeterminado")).lower()
            if r not in colores_riesgo: r = 'indeterminado'
            desc = str(m.get("descripcion_breve", "Alteración")).strip()
            
            if r not in tipos_presentes:
                tipos_presentes[r] = []
            if desc and desc not in tipos_presentes[r]:
                tipos_presentes[r].append(desc)

        def calc_y(lineas):
            h = 20 * escala
            for item in lineas:
                h += len(textwrap.wrap(f"• {item}", width=col_w)) * (16 * escala)
            return h + (20 * escala)

        h_c1 = (45*escala) + calc_y(datos_t) + calc_y([f"K+: {analisis_hallazgos.get('k_estimado', '')}", f"Ca2+: {analisis_hallazgos.get('ca_estimado', '')}"]) + (len(tipos_presentes) * 60 * escala) + (40*escala)
        h_c2 = (45*escala) + calc_y(lista_h)
        h_c3 = (45*escala) + calc_y([str(analisis_hallazgos.get("etiologia", ""))]) + calc_y(manejo)

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

        y_c1 = render_txt(c1_x, int(45 * escala), "DATOS TÉCNICOS:", datos_t)
        y_c1 = render_txt(c1_x, y_c1, "IONOGRAMA ESTIMADO:", [f"K+: {analisis_hallazgos.get('k_estimado', '')}", f"Ca2+: {analisis_hallazgos.get('ca_estimado', '')}"])
        
        if tipos_presentes:
            draw.text((c1_x, y_c1), "LEYENDA DE COLORES:", fill=(40, 80, 140), font=f_sub)
            y_c1 += int(20 * escala)
            for r, desc_list in tipos_presentes.items():
                rgba, desc_base = colores_riesgo[r]
                # Ahora mostramos TODAS las descripciones asociadas a este nivel de riesgo, sin cortar.
                txt_leyenda = f"{desc_base}: {', '.join(desc_list)}" if desc_list else desc_base
                
                r_size = int(10 * escala)
                draw_ov.ellipse([c1_x, y_c1+int(2*escala), c1_x+r_size, y_c1+r_size+int(2*escala)], fill=rgba)
                
                for p in textwrap.wrap(txt_leyenda, width=col_w - 2):
                    draw.text((c1_x + int(22 * escala), y_c1), p, fill=(50, 50, 50), font=f_texto)
                    y_c1 += int(16 * escala)
                y_c1 += int(12 * escala) # Espacio extra entre diferentes niveles de riesgo

        render_txt(c2_x, int(45 * escala), "HALLAZGOS CLAVE:", lista_h)
        y_c3 = render_txt(c3_x, int(45 * escala), "ETIOLOGÍA (Diferenciales):", [str(analisis_hallazgos.get("etiologia", "N/A"))])
        render_txt(c3_x, y_c3, "MANEJO CLÍNICO Y FÁRMACOS (Guías SAC/SAE):", manejo)

        for m in marcas_ia:
            try:
                r = str(m.get("nivel_riesgo", "indeterminado")).lower()
                if r not in colores_riesgo: r = 'indeterminado'
                px = int(w_orig * (min(max(float(m.get("x_porcentaje", 50)), 0), 100) / 100.0))
                py = int(h_orig * (min(max(float(m.get("y_porcentaje", 50)), 0), 100) / 100.0))
                
                # Tamaño de la marca reducido y transparente como lo pediste
                rad = int(12 * escala)
                draw_ov.ellipse([px-rad, py-rad, px+rad, py+rad], fill=colores_riesgo[r][0])
            except: continue

        img_final = Image.alpha_composite(img_final.convert("RGBA"), c_overlay).convert("RGB")
        buf = io.BytesIO()
        img_final.save(buf, format="PNG", compress_level=0)
        buf.seek(0)
        return send_file(buf, mimetype="image/png")

    except Exception as e:
        return {"error": f"Error render: {str(e)}"}, 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
