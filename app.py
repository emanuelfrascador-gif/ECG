import io
import base64
from flask import Flask, request, send_file
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)
# Sin restricciones de tamaño para cadenas largas en JSON
app.config['MAX_CONTENT_LENGTH'] = 60 * 1024 * 1024

@app.route("/", methods=["GET"])
def home():
    return "API de Procesamiento de ECG funcionando correctamente."

@app.route("/analizar", methods=["POST"])
def analizar_ecg():
    # Recibimos los datos en formato JSON (force=True asegura que lo lea aunque App Inventor no envíe cabeceras)
    data = request.get_json(silent=True, force=True)
    if not data or "image" not in data:
        return {"error": "No se encontró la imagen en formato JSON"}, 400
    
    try:
        # Decodificamos el string Base64 a bytes puros de imagen
        image_data = base64.b64decode(data["image"])
        uploaded_file = io.BytesIO(image_data)
    except Exception as e:
        return {"error": "Error al decodificar Base64"}, 400

    # --- TODO TU DISEÑO Y LÓGICA ORIGINAL INTACTOS ---
    ecg_orig = Image.open(uploaded_file).convert("RGB")
    w_orig, h_orig = ecg_orig.size

    ancho_panel = 1050
    alto_final = h_orig 
    
    imagen_final = Image.new("RGB", (w_orig + ancho_panel, alto_final), color=(255, 255, 255))
    imagen_final.paste(ecg_orig, (0, 0))

    capa_overlay = Image.new("RGBA", (w_orig + ancho_panel, alto_final), (255, 255, 255, 0))
    draw_overlay = ImageDraw.Draw(capa_overlay)

    analisis_hallazgos = {
        "datos_tecnicos": "Calibracion: 25 mm/s, 10 mm/mV | Ritmo Sinusal.",
        "lista_hallazgos": [
            "Trastorno de conduccion intraventricular derecho.",
            "Criterios de alto voltaje compatibles con HVI.",
            "Alteraciones morfologicas de la onda P.",
            "Presencia de extrasistoles ventriculares (ESV)."
        ],
        "leyenda": [
            ((178, 60, 60), "HVI: Derivadas V2-V5.", "Sv2+Rv5 <= 35mm"),
            ((50, 120, 200), "Conduccion: QRS ancho V1-V2.", "QRS < 0.12 s"),
            ((200, 160, 30), "Auricular: Onda P frontal.", "Duracion < 0.11 s"),
            ((50, 160, 50), "Repolarizacion ST/T.", "ST isoelectrico")
        ],
        "etiologia": "Compatible con HTA cronica y sobrecarga.",
        "mini_ionograma": {
            "K_estimado": "Normokalemia (sin T picudas).",
            "Ca_estimado": "QT adaptado normal."
        },
        "manejo_sac": (
            "1. Control PA: IECA (Enalapril) o ARA II (Losartan).\n"
            "2. Proteccion Cardioprotectora: Bloqueantes calcicos.\n"
            "3. Arritmias / ESV: Beta-bloqueantes si hay sintomas.\n"
            "4. Estudios: Ecocardiograma Doppler y Holter 24h."
        )
    }

    draw = ImageDraw.Draw(imagen_final)
    try:
        f_titulo = ImageFont.truetype("DejaVuSans-Bold.ttf", 16)
        f_sub = ImageFont.truetype("DejaVuSans-Bold.ttf", 11)
        f_texto = ImageFont.truetype("DejaVuSans.ttf", 10)
        f_rojo = ImageFont.truetype("DejaVuSans-Bold.ttf", 10)
    except:
        f_titulo = f_sub = f_texto = f_rojo = ImageFont.load_default()

    col1_x = w_orig + 15
    col2_x = w_orig + 535
    margen_sup = 15
    espacio_bloque = 12 
    espacio_item = 12

    draw.line([(w_orig, 0), (w_orig, alto_final)], fill=(180, 180, 180), width=2)
    draw.text((col1_x, margen_sup), "RESENA CARDIOLOGICA Y MANEJO CLINICO (GUIAS SAC)", fill=(10, 40, 90), font=f_titulo)
    draw.line([(col1_x, margen_sup + 22), (w_orig + ancho_panel - 15, margen_sup + 22)], fill=(200, 200, 200), width=1)

    def dibujar_bloque_compacto(x, y, titulo_bloque, lineas, es_lista=False):
        draw.text((x, y), titulo_bloque, fill=(10, 40, 80), font=f_sub)
        y += espacio_bloque + 2 
        if es_lista:
            for idx, item in enumerate(lineas):
                if isinstance(item, tuple):
                    color_rgb, texto_item, valor_normal = item
                    draw.ellipse([x + 2, y + 2, x + 10, y + 10], fill=color_rgb, outline=color_rgb)
                    draw.text((x + 16, y), texto_item, fill=(30, 30, 30), font=f_texto)
                    draw.text((x + 260, y), f"Norm: {valor_normal}", fill=(200, 30, 30), font=f_rojo)
                else:
                    draw.text((x, y), f"{idx+1}. {item}", fill=(30, 30, 30), font=f_texto)
                y += espacio_item
        else:
            for item in lineas:
                draw.text((x, y), item, fill=(30, 30, 30), font=f_texto)
                y += espacio_item
        return y + (espacio_bloque / 2)

    y_c1 = margen_sup + 35
    y_c1 = dibujar_bloque_compacto(col1_x, y_c1, "DATOS TECNICOS Y HALLAZGOS:", [analisis_hallazgos["datos_tecnicos"]] + analisis_hallazgos["lista_hallazgos"])
    y_c1 = dibujar_bloque_compacto(col1_x, y_c1, "LEYENDA Y PARAMETROS:", analisis_hallazgos["leyenda"], es_lista=True)

    y_c2 = margen_sup + 35
    y_c2 = dibujar_bloque_compacto(col2_x, y_c2, "ETIOLOGIA Y CORRELACION:", [analisis_hallazgos["etiologia"]])
    y_c2 = dibujar_bloque_compacto(col2_x, y_c2, "MINI-IONOGRAMA:", 
                                    [f"- K+: {analisis_hallazgos['mini_ionograma']['K_estimado']}",
                                     f"- Ca2+: {analisis_hallazgos['mini_ionograma']['Ca_estimado']}"])
    y_c2 = dibujar_bloque_compacto(col2_x, y_c2, "MANEJO CLINICO Y FARMACOS (GUIAS SAC):", analisis_hallazgos["manejo_sac"].split('\n'))

    puntos_marcar = [
        (int(w_orig * 0.63), int(h_orig * 0.73), (178, 60, 60, 100)),
        (int(w_orig * 0.93), int(h_orig * 0.74), (178, 60, 60, 100)),
        (int(w_orig * 0.33), int(h_orig * 0.17), (50, 120, 200, 100)),
        (int(w_orig * 0.12), int(h_orig * 0.14), (200, 160, 30, 100)),
    ]
    for px, py, rgba in puntos_marcar:
        r = 12
        draw_overlay.ellipse([px-r, py-r, px+r, py+r], fill=rgba, outline=rgba)
    
    imagen_final = Image.alpha_composite(imagen_final.convert("RGBA"), capa_overlay).convert("RGB")
    # --------------------------------------------------------

    buf = io.BytesIO()
    imagen_final.save(buf, format="PNG", compress_level=0)
    buf.seek(0)

    return send_file(buf, mimetype="image/png")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
