import io
import os
import base64
import json
import time
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

    ecg_orig.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    w_orig, h_orig = ecg_orig.size

    prompt_maestro = (
        "Analiza este ECG. Devuelve SOLO un JSON válido sin formato Markdown. Claves exactas: "
        "'datos_tecnicos', 'lista_hallazgos' (array), 'etiologia', 'k_estimado', 'ca_estimado', "
        "'manejo_sac', 'marcas' (array de objetos con x_porcentaje, y_porcentaje, tipo)."
    )

    # AUTODESCUBRIMIENTO DE MODELOS: Busca qué modelos tenés habilitados realmente
    modelos_autorizados = []
    try:
        print("Buscando modelos Flash autorizados para tu API key...", flush=True)
        for m in client.models.list():
            nombre = m.name.replace('models/', '')
            if 'flash' in nombre.lower():
                modelos_autorizados.append(nombre)
        print(f"Modelos permitidos detectados: {modelos_autorizados}", flush=True)
    except Exception as e:
        print(f"Fallo listando modelos: {e}", flush=True)
    
    if not modelos_autorizados:
        # Fallback de emergencia a modelos recientes
        modelos_autorizados = ['gemini-2.0-flash', 'gemini-3.1-flash', 'gemini-2.5-flash']

    analisis_hallazgos = None
    ultimo_error = ""

    for modelo in modelos_autorizados:
        try:
            print(f"Llamando a {modelo}...", flush=True)
            response = client.models.generate_content(
                model=modelo,
                contents=[ecg_orig, prompt_maestro],
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
            )
            texto_limpio = response.text.replace("```json", "").replace("```", "").strip()
            analisis_hallazgos = json.loads(texto_limpio)
            print(f"Éxito absoluto con {modelo}", flush=True)
            break
        except Exception as e:
            ultimo_error = str(e)
            print(f"Fallo en {modelo}: {ultimo_error}", flush=True)
            time.sleep(1)

    if not analisis_hallazgos:
        return {"error": f"IA falló en todos los modelos. Último error: {ultimo_error}"}, 500

    try:
        ancho_panel = 680
        imagen_final = Image.new("RGB", (w_orig + ancho_panel, h_orig), color=(255, 255, 255))
        imagen_final.paste(ecg_orig, (0, 0))
        capa_overlay = Image.new("RGBA", (w_orig + ancho_panel, h_orig), (255, 255, 255, 0))
        draw_overlay = ImageDraw.Draw(capa_overlay)
        draw = ImageDraw.Draw(imagen_final)
        
        try:
            f_titulo = ImageFont.truetype("DejaVuSans-Bold.ttf", 14)
            f_sub = ImageFont.truetype("DejaVuSans-Bold.ttf", 10)
            f_texto = ImageFont.truetype("DejaVuSans.ttf", 9)
        except:
            f_titulo = f_sub = f_texto = ImageFont.load_default()

        col_x = w_orig + 15
        y_actual = 12
        draw.line([(w_orig, 0), (w_orig, h_orig)], fill=(210, 210, 210), width=1)
        draw.text((col_x, y_actual), "RESEÑA CARDIOLÓGICA", fill=(15, 45, 95), font=f_titulo)
        y_actual += 28

        def dibujar_seccion(y, titulo, lineas):
            draw.text((col_x, y), titulo, fill=(20, 50, 90), font=f_sub)
            y += 10
            for item in lineas:
                draw.text((col_x, y), f"• {str(item)}", fill=(40, 40, 40), font=f_texto)
                y += 11
            return y + 8

        datos_t = str(analisis_hallazgos.get("datos_tecnicos", "N/A"))
        lista_h = analisis_hallazgos.get("lista_hallazgos")
        if not isinstance(lista_h, list): lista_h = [str(lista_h)] if lista_h else ["Sin hallazgos"]
        
        y_actual = dibujar_seccion(y_actual, "DATOS Y HALLAZGOS:", [datos_t] + lista_h)
        y_actual = dibujar_seccion(y_actual, "ETIOLOGÍA:", [str(analisis_hallazgos.get("etiologia", "N/A"))])
        y_actual = dibujar_seccion(y_actual, "IONOGRAMA:", [f"K+: {analisis_hallazgos.get('k_estimado', '')}", f"Ca2+: {analisis_hallazgos.get('ca_estimado', '')}"])
        dibujar_seccion(y_actual, "MANEJO:", str(analisis_hallazgos.get("manejo_sac", "N/A")).split('\n'))

        colores = {'hvi': (178, 60, 60, 100), 'conduccion': (50, 120, 200, 100), 'onda_p': (200, 160, 30, 100), 'st_t': (50, 160, 50, 100)}
        for m in analisis_hallazgos.get("marcas", []):
            try:
                px = int(w_orig * (min(max(float(m.get("x_porcentaje", 50)), 0), 100) / 100.0))
                py = int(h_orig * (min(max(float(m.get("y_porcentaje", 50)), 0), 100) / 100.0))
                rgba = colores.get(str(m.get("tipo", "hvi")).lower(), (178, 60, 60, 100))
                draw_overlay.ellipse([px-12, py-12, px+12, py+12], fill=rgba, outline=rgba)
            except: continue

        imagen_final = Image.alpha_composite(imagen_final.convert("RGBA"), capa_overlay).convert("RGB")
        buf = io.BytesIO()
        imagen_final.save(buf, format="PNG", compress_level=0)
        buf.seek(0)
        return send_file(buf, mimetype="image/png")

    except Exception as e:
        print(f"Error renderizando imagen: {str(e)}", flush=True)
        return {"error": f"Fallo al procesar imagen: {str(e)}"}, 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
