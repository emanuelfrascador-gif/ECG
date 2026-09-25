import io
import os
import base64
import json
from flask import Flask, request, send_file
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 60 * 1024 * 1024

client = genai.Client()

@app.route("/", methods=["GET"])
def home():
    return "API de Procesamiento con IA Real Activa."

@app.route("/analizar", methods=["POST"])
def analizar_ecg():
    data = request.get_json(silent=True, force=True)
    
    imagen_base64 = None
    if isinstance(data, dict):
        imagen_base64 = data.get("image") or data.get("Image")
    
    if not imagen_base64:
        cuerpo_crudo = request.data.decode("utf-8", errors="ignore").strip()
        if cuerpo_crudo:
            imagen_base64 = (cuerpo_crudo
                             .replace('{"image":"', '')
                             .replace('{"Image":"', '')
                             .replace('image=', '')
                             .rstrip('"}')
                             .strip())

    if not imagen_base64:
        return {"error": "No se encontró la imagen en los datos recibidos"}, 400
    
    try:
        image_data = base64.b64decode(imagen_base64)
        uploaded_file = io.BytesIO(image_data)
    except Exception as e:
        return {"error": "Error al decodificar Base64"}, 400

    try:
        ecg_orig = Image.open(uploaded_file).convert("RGB")
    except Exception as e:
        try:
            if b"," in image_data:
                image_data = image_data.split(b",", 1)[1]
                uploaded_file = io.BytesIO(image_data)
                ecg_orig = Image.open(uploaded_file).convert("RGB")
            else:
                raise e
        except Exception as e2:
            return {"error": f"Imagen no válida: {str(e2)}"}, 400

    w_orig, h_orig = ecg_orig.size

    # --- LLAMADA REAL A LA IA CON PROMPT MAESTRO SAC ---
    prompt_maestro = (
        "Actúa como un médico cardiólogo experto bajo Guías de la Sociedad Argentina de Cardiología (SAC). "
        "Analiza esta tira de ECG real. "
        "Devuelve la respuesta estrictamente en un JSON plano con estas claves exactas:\n"
        "1. 'datos_tecnicos': string con calibración, ritmo y eje.\n"
        "2. 'lista_hallazgos': lista de strings con hallazgos reales de esta imagen.\n"
        "3. 'etiologia': string con correlación clínica.\n"
        "4. 'k_estimado': string con estado del potasio según ondas T.\n"
        "5. 'ca_estimado': string con estado del calcio y QT.\n"
        "6. 'manejo_sac': string con nombres de fármacos específicos y dosis exactas (ej: Enalapril 10 mg/día) según SAC.\n"
        "7. 'marcas': lista de objetos con 'x_porcentaje' (0-100), 'y_porcentaje' (0-100) exactos de las alteraciones sobre el trazo, y 'tipo' ('hvi', 'conduccion', 'onda_p', 'st_t')."
    )

    analisis_hallazgos = {}
    try:
        print("Enviando imagen a Gemini para análisis clínico real...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[ecg_orig, prompt_maestro],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        print("Respuesta recibida de Gemini:", response.text[:200])
        analisis_hallazgos = json.loads(response.text)
    except Exception as e:
        print("ERROR CRÍTICO LLAMANDO A GEMINI:", str(e))
        return {"error": f"Fallo en la IA: {str(e)}"}, 500

    ancho_panel = 680
    alto_final = h_orig 
    
    imagen_final = Image.new("RGB", (w_orig + ancho_panel, alto_final), color=(255, 255, 255))
    imagen_final.paste(ecg_orig, (0, 0))

    capa_overlay = Image.new("RGBA", (w_orig + ancho_panel, alto_final), (255, 255, 255, 0))
    draw_overlay = ImageDraw.Draw(capa_overlay)

    draw = ImageDraw.Draw(imagen_final)
    try:
        f_titulo = ImageFont.truetype("DejaVuSans-Bold.ttf", 14)
        f_sub = ImageFont.truetype("DejaVuSans-Bold.ttf", 10)
        f_texto = ImageFont.truetype("DejaVuSans.ttf", 9)
    except:
        f_titulo = f_sub = f_texto = ImageFont.load_default()

    col_x = w_orig + 15
    margen_sup = 12
    espacio_bloque = 8
    espacio_item = 11

    draw.line([(w_orig, 0), (w_orig, alto_final)], fill=(210, 210, 210), width=1)
    draw.text((col_x, margen_sup), "RESEÑA CARDIOLÓGICA Y MANEJO (GUÍAS SAC)", fill=(15, 45, 95), font=f_titulo)
    draw.line([(col_x, margen_sup + 18), (w_orig + ancho_panel - 15, margen_sup + 18)], fill=(220, 220, 220), width=1)

    def dibujar_seccion_compacta(y, titulo_seccion, lineas):
        draw.text((col_x, y), titulo_seccion, fill=(20, 50, 90), font=f_sub)
        y += espacio_bloque + 2
        for item in lineas:
            draw.text((col_x, y), f"• {item}", fill=(40, 40, 40), font=f_texto)
            y += espacio_item
        return y + espacio_bloque

    tek_datos = analisis_hallazgos.get("datos_tecnicos", "Ritmo Sinusal")
    lst_hall = analisis_hallazgos.get("lista_hallazgos", [])
    etiq = analisis_hallazgos.get("etiologia", "Sin especificar")
    k_est = analisis_hallazgos.get("k_estimado", "Normal")
    ca_est = analisis_hallazgos.get("ca_estimado", "Normal")
    manejo = analisis_hallazgos.get("manejo_sac", "Seguir indicaciones médicas.")
    marcas_ia = analisis_hallazgos.get("marcas", [])

    y_actual = margen_sup + 28
    y_actual = dibujar_seccion_compacta(y_actual, "DATOS TÉCNICOS Y HALLAZGOS CLÍNICOS:", [tek_datos] + lst_hall)
    y_actual = dibujar_seccion_compacta(y_actual, "ETIOLOGÍA Y CORRELACIÓN:", [etiq])
    y_actual = dibujar_seccion_compacta(y_actual, "MINI-IONOGRAMA ESTIMADO:", [f"K+: {k_est}", f"Ca2+ / QT: {ca_est}"])
    y_actual = dibujar_seccion_compacta(y_actual, "MANEJO CLÍNICO Y FARMACOLOGÍA (SAC):", manejo.split('\n'))

    colores_map = {
        'hvi': (178, 60, 60, 100),       
        'conduccion': (50, 120, 200, 100), 
        'onda_p': (200, 160, 30, 100),     
        'st_t': (50, 160, 50, 100)         
    }

    for m in marcas_ia:
        try:
            x_pct = float(m.get("x_porcentaje", 50))
            y_pct = float(m.get("y_porcentaje", 50))
            
            if x_pct > 100: x_pct = 100
            if x_pct < 0: x_pct = 0
            if y_pct > 100: y_pct = 100
            if y_pct < 0: y_pct = 0

            px = int(w_orig * (x_pct / 100.0))
            py = int(h_orig * (y_pct / 100.0))

            tipo = m.get("tipo", "hvi")
            rgba = colores_map.get(tipo, (178, 60, 60, 100))
            
            r = 12
            draw_overlay.ellipse([px-r, py-r, px+r, py+r], fill=rgba, outline=rgba)
        except:
            continue

    imagen_final = Image.alpha_composite(imagen_final.convert("RGBA"), capa_overlay).convert("RGB")

    buf = io.BytesIO()
    imagen_final.save(buf, format="PNG", compress_level=0)
    buf.seek(0)

    return send_file(buf, mimetype="image/png")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
