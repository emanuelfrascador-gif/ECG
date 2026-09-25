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
        "'datos_tecnicos' (array de strings, formato 'Medida: Valor (Normal: Rango)'), "
        "'lista_hallazgos' (array), 'riesgo_quirurgico' (string), "
        "'etiologia' (string), 'k_estimado' (string), 'ca_estimado' (string), "
        "'manejo_sac' (string), 'marcas' (array de objetos con x_porcentaje, y_porcentaje, tipo, descripcion_breve). "
        "REGLAS CRÍTICAS: "
        "1. 'tipo' solo puede ser: 'hvi', 'conduccion', 'onda_p', 'st_t'. "
        "2. 'descripcion_breve' debe indicar la alteración exacta (ej: 'Infradesnivel ST 2mm', 'Onda P Mitral'). "
        "3. Coordenadas apuntando sobre la anomalía en el papel milimetrado."
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
        ancho_panel = 920
        col_w = 42  
        
        dt = analisis_hallazgos.get("datos_tecnicos", [])
        datos_t = [str(x) for x in dt] if isinstance(dt, list) else [str(dt)]
        lista_h = analisis_hallazgos.get("lista_hallazgos", [])
        if not isinstance(lista_h, list): lista_h = [str(lista_h)]
        lista_h.append(f"RIESGO QUIRÚRGICO: {analisis_hallazgos.get('riesgo_quirurgico', 'No evaluado')}")
        manejo = str(analisis_hallazgos.get("manejo_sac", "N/A")).split('\n')
        
        marcas_ia = analisis_hallazgos.get("marcas", [])
        colores_map = {
            'hvi': ((220, 50, 50, 130), 'HVI / Sobrecarga'),       
            'conduccion': ((50, 120, 220, 130), 'Conducción'), 
            'onda_p': ((220, 180, 50, 130), 'Anomalía Onda P'),     
            'st_t': ((50, 180, 50, 130), 'Alteración ST-T')         
        }

        tipos_presentes = {}
        for m in marcas_ia:
            t = str(m.get("tipo", "")).lower()
            desc = str(m.get("descripcion_breve", "")).strip()
            if t in colores_map:
                if t not in tipos_presentes:
                    tipos_presentes[t] = []
                if desc and desc not in tipos_presentes[t]:
                    tipos_presentes[t].append(desc)

        # Cálculo dinámico exacto de altura
        def calc_y(lineas):
            h = 20
            for item in lineas:
                h += len(textwrap.wrap(f"• {item}", width=col_w)) * 16
            return h + 20

        h_c1 = 45 + calc_y(datos_t) + calc_y([f"K+: {analisis_hallazgos.get('k_estimado', '')}", f"Ca2+: {analisis_hallazgos.get('ca_estimado', '')}"]) + (len(tipos_presentes) * 45) + 40
        h_c2 = 45 + calc_y(lista_h)
        h_c3 = 45 + calc_y([str(analisis_hallazgos.get("etiologia", ""))]) + calc_y(manejo)

        alto_final = int(max(h_orig, h_c1, h_c2, h_c3))
        
        img_final = Image.new("RGB", (w_orig + ancho_panel, alto_final), color=(248, 248, 250))
        img_final.paste(ecg_orig, (0, 0))
        
        c_overlay = Image.new("RGBA", img_final.size, (255, 255, 255, 0))
        draw_ov = ImageDraw.Draw(c_overlay)
        draw = ImageDraw.Draw(img_final)

        try:
            f_titulo = ImageFont.truetype("DejaVuSans-Bold.ttf", 16)
            f_sub = ImageFont.truetype("DejaVuSans-Bold.ttf", 12)
            f_texto = ImageFont.truetype("DejaVuSans.ttf", 11)
        except:
            f_titulo = f_sub = f_texto = ImageFont.load_default()

        c1_x, c2_x, c3_x = w_orig + 15, w_orig + 315, w_orig + 615
        draw.line([(w_orig, 0), (w_orig, alto_final)], fill=(200, 200, 200), width=1)
        draw.text((c1_x, 15), "RESEÑA CARDIOLÓGICA PROFUNDA Y MANEJO CLÍNICO", fill=(20, 50, 100), font=f_titulo)
        draw.line([(c1_x, 35), (w_orig + ancho_panel - 15, 35)], fill=(220, 220, 220), width=1)

        def render_txt(x, y, titulo, lineas):
            draw.text((x, y), titulo, fill=(40, 80, 140), font=f_sub)
            y += 20  
            for item in lineas:
                for p in textwrap.wrap(f"• {item}", width=col_w):
                    draw.text((x, y), p, fill=(50, 50, 50), font=f_texto)
                    y += 16  
            return y + 20

        y_c1 = render_txt(c1_x, 45, "DATOS TÉCNICOS:", datos_t)
        y_c1 = render_txt(c1_x, y_c1, "IONOGRAMA ESTIMADO:", [f"K+: {analisis_hallazgos.get('k_estimado', '')}", f"Ca2+: {analisis_hallazgos.get('ca_estimado', '')}"])
        
        if tipos_presentes:
            draw.text((c1_x, y_c1), "LEYENDA DE COLORES:", fill=(40, 80, 140), font=f_sub)
            y_c1 += 20
            for t, desc_list in tipos_presentes.items():
                rgba, desc_base = colores_map[t]
                txt_leyenda = f"{desc_base}: {', '.join(desc_list[:2])}" if desc_list else desc_base
                draw_ov.ellipse([c1_x, y_c1+2, c1_x+12, y_c1+14], fill=rgba)
                for p in textwrap.wrap(txt_leyenda, width=col_w - 2):
                    draw.text((c1_x + 22, y_c1), p, fill=(50, 50, 50), font=f_texto)
                    y_c1 += 16
                y_c1 += 8

        render_txt(c2_x, 45, "HALLAZGOS CLAVE:", lista_h)
        y_c3 = render_txt(c3_x, 45, "ETIOLOGÍA:", [str(analisis_hallazgos.get("etiologia", "N/A"))])
        render_txt(c3_x, y_c3, "MANEJO CLÍNICO Y TRATAMIENTO:", manejo)

        for m in marcas_ia:
            try:
                t = str(m.get("tipo", "")).lower()
                if t not in colores_map: continue
                px = int(w_orig * (min(max(float(m.get("x_porcentaje", 50)), 0), 100) / 100.0))
                py = int(h_orig * (min(max(float(m.get("y_porcentaje", 50)), 0), 100) / 100.0))
                draw_ov.ellipse([px-22, py-22, px+22, py+22], fill=colores_map[t][0])
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
