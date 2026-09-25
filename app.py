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
    data = request.get_json(silent=True, force=True)
    imagen_base64 = data.get("image") or data.get("Image") if isinstance(data, dict) else None
    
    if not imagen_base64:
        cuerpo_crudo = request.data.decode("utf-8", errors="ignore").strip()
        if cuerpo_crudo:
            imagen_base64 = cuerpo_crudo.replace('{"image":"', '').replace('{"Image":"', '').replace('image=', '').rstrip('"}').strip()

    if not imagen_base64:
        return {"error": "No se encontró imagen"}, 400
    
    try:
        image_data = base64.b64decode(imagen_base64)
        ecg_orig = Image.open(io.BytesIO(image_data)).convert("RGB")
    except Exception:
        try:
            if b"," in image_data:
                image_data = image_data.split(b",", 1)[1]
                ecg_orig = Image.open(io.BytesIO(image_data)).convert("RGB")
            else:
                return {"error": "Formato inválido"}, 400
        except Exception as e:
            return {"error": f"Error base64: {str(e)}"}, 400

    ecg_orig.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    w_orig, h_orig = ecg_orig.size

    prompt_maestro = (
        "Analiza este ECG. Devuelve SOLO un JSON válido. Claves exactas: "
        "'datos_tecnicos', 'lista_hallazgos' (array), 'etiologia', 'k_estimado', 'ca_estimado', "
        "'manejo_sac', 'marcas' (array de objetos con x_porcentaje, y_porcentaje, tipo). "
        "REGLA CRÍTICA DE MARCAS: Coordenadas (0-100) DEBEN LIMITARSE EXCLUSIVAMENTE a la zona del papel milimetrado. "
        "Ignora fondos negros, mesas o bordes. Apunta exactamente sobre la anomalía."
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
            break
        except Exception:
            time.sleep(1)

    if not analisis_hallazgos:
        return {"error": "IA falló en todos los modelos."}, 500

    try:
        ancho_panel = 920
        col_w = 42  # Caracteres por línea para encastre compacto
        
        datos_t = str(analisis_hallazgos.get("datos_tecnicos", "N/A"))
        lista_h = analisis_hallazgos.get("lista_hallazgos", [])
        if not isinstance(lista_h, list): lista_h = [str(lista_h)]
        manejo = str(analisis_hallazgos.get("manejo_sac", "N/A")).split('\n')
        
        colores = {
            'hvi': (220, 50, 50, 120),       
            'conduccion': (50, 120, 220, 120), 
            'onda_p': (220, 180, 50, 120),     
            'st_t': (50, 180, 50, 120)         
        }

        try:
            f_titulo = ImageFont.truetype("DejaVuSans-Bold.ttf", 16)
            f_sub = ImageFont.truetype("DejaVuSans-Bold.ttf", 12)
            f_texto = ImageFont.truetype("DejaVuSans.ttf", 11)
        except:
            f_titulo = f_sub = f_texto = ImageFont.load_default()

        # Coordenadas de las 3 columnas
        c1_x = w_orig + 15
        c2_x = w_orig + 315
        c3_x = w_orig + 615

        alto_final = max(h_orig, 450)
        img_final = Image.new("RGB", (w_orig + ancho_panel, alto_final), color=(248, 248, 250))
        img_final.paste(ecg_orig, (0, 0))
        
        c_overlay = Image.new("RGBA", img_final.size, (255, 255, 255, 0))
        draw_ov = ImageDraw.Draw(c_overlay)
        draw = ImageDraw.Draw(img_final)

        draw.line([(w_orig, 0), (w_orig, alto_final)], fill=(200, 200, 200), width=1)
        draw.text((c1_x, 15), "RESEÑA CARDIOLÓGICA PROFUNDA Y MANEJO CLÍNICO", fill=(20, 50, 100), font=f_titulo)
        draw.line([(c1_x, 35), (w_orig + ancho_panel - 15, 35)], fill=(220, 220, 220), width=1)

        def render_txt(x, y, titulo, lineas):
            draw.text((x, y), titulo, fill=(40, 80, 140), font=f_sub)
            y += 18
            for item in lineas:
                for p in textwrap.wrap(f"• {item}", width=col_w):
                    draw.text((x, y), p, fill=(50, 50, 50), font=f_texto)
                    y += 14
            return y + 15

        # Columna 1: Datos y Leyenda
        y_c1 = render_txt(c1_x, 45, "DATOS TÉCNICOS:", [datos_t])
        y_c1 = render_txt(c1_x, y_c1, "IONOGRAMA ESTIMADO:", [f"K+: {analisis_hallazgos.get('k_estimado', '')}", f"Ca2+: {analisis_hallazgos.get('ca_estimado', '')}"])
        
        draw.text((c1_x, y_c1), "LEYENDA DE COLORES:", fill=(40, 80, 140), font=f_sub)
        y_c1 += 18
        for k, v in [('hvi', 'HVI / Sobrecarga'), ('conduccion', 'Trastorno Conducción'), ('onda_p', 'Anomalía Onda P'), ('st_t', 'Alteración ST-T')]:
            draw_ov.ellipse([c1_x, y_c1+2, c1_x+10, y_c1+12], fill=colores.get(k))
            draw.text((c1_x + 18, y_c1), v, fill=(50, 50, 50), font=f_texto)
            y_c1 += 16

        # Columna 2: Hallazgos
        render_txt(c2_x, 45, "HALLAZGOS CLAVE:", lista_h)

        # Columna 3: Etiología y Manejo
        y_c3 = render_txt(c3_x, 45, "ETIOLOGÍA:", [str(analisis_hallazgos.get("etiologia", "N/A"))])
        render_txt(c3_x, y_c3, "MANEJO CLÍNICO Y TRATAMIENTO:", manejo)

        # Marcas sobre ECG
        for m in analisis_hallazgos.get("marcas", []):
            try:
                px = int(w_orig * (min(max(float(m.get("x_porcentaje", 50)), 0), 100) / 100.0))
                py = int(h_orig * (min(max(float(m.get("y_porcentaje", 50)), 0), 100) / 100.0))
                rgba = colores.get(str(m.get("tipo", "hvi")).lower(), (220, 50, 50, 120))
                draw_ov.ellipse([px-20, py-20, px+20, py+20], fill=rgba)
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
