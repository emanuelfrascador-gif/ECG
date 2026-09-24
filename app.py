import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import io
import streamlit as st


# --- CONTROL DE ENTRADA API (MIT APP INVENTOR) ---
modo_api = st.query_params.get("mode") == "api"

if not modo_api:
    st.title("⚡ Analizador ECG SAC - Panel Clínico Integrado")
    st.write("Sube tu tira de ECG para generar el panel compacto optimizado (Guías SAC).")

uploaded_file = st.file_uploader("Seleccionar archivo de ECG", type=["jpg", "jpeg", "png"])
# Desactiva las llamadas a localStorage que rompen en el WebViewer
st.set_option('client.toolbarMode', 'minimal')

st.set_page_config(page_title="Analizador ECG SAC", layout="wide")

if uploaded_file is not None:
    # Cargar imagen original
    ecg_orig = Image.open(uploaded_file).convert("RGB")
    w_orig, h_orig = ecg_orig.size

    # --- DISEÑO COMPACTO PROPORCIONAL (AJUSTADO PARA EVITAR ESPACIOS BLANCOS) ---
    ancho_panel = 1050
    # Ajustamos la altura final al tamaño exacto de la tira para no generar vacíos innecesarios
    alto_final = h_orig 
    
    imagen_final = Image.new("RGB", (w_orig + ancho_panel, alto_final), color=(255, 255, 255))
    imagen_final.paste(ecg_orig, (0, 0))

    capa_overlay = Image.new("RGBA", (w_orig + ancho_panel, alto_final), (255, 255, 255, 0))
    draw_overlay = ImageDraw.Draw(capa_overlay)

    # Datos clínicos estructurados Guías SAC (Tu estructura original intacta)
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

    # Dibujado optimizado para fuentes limpias
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

    # Línea divisoria vertical exacta
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

    # Distribución en 2 columnas equilibradas y compactas
    y_c1 = margen_sup + 35
    y_c1 = dibujar_bloque_compacto(col1_x, y_c1, "DATOS TECNICOS Y HALLAZGOS:", [analisis_hallazgos["datos_tecnicos"]] + analisis_hallazgos["lista_hallazgos"])
    y_c1 = dibujar_bloque_compacto(col1_x, y_c1, "LEYENDA Y PARAMETROS:", analisis_hallazgos["leyenda"], es_lista=True)

    y_c2 = margen_sup + 35
    y_c2 = dibujar_bloque_compacto(col2_x, y_c2, "ETIOLOGIA Y CORRELACION:", [analisis_hallazgos["etiologia"]])
    y_c2 = dibujar_bloque_compacto(col2_x, y_c2, "MINI-IONOGRAMA:", 
                                    [f"- K+: {analisis_hallazgos['mini_ionograma']['K_estimado']}",
                                     f"- Ca2+: {analisis_hallazgos['mini_ionograma']['Ca_estimado']}"])
    y_c2 = dibujar_bloque_compacto(col2_x, y_c2, "MANEJO CLINICO Y FARMACOS (GUIAS SAC):", analisis_hallazgos["manejo_sac"].split('\n'))

    # Marcar sutilmente sobre el ECG
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

    # Guardar en buffer
    buf = io.BytesIO()
    imagen_final.save(buf, format="PNG", compress_level=0)
    byte_im = buf.getvalue()

    # Si la app de App Inventor lo pide por API, devuelve los bytes directos
    if modo_api:
        st.write(byte_im)
    else:
        # Mostrar vista previa normal en la web
        st.image(imagen_final, caption="Panel Clínico Optimizado y Compacto", use_container_width=True)
        st.download_button(
            label="📥 Descargar Imagen Compacta Definitiva",
            data=byte_im,
            file_name="ecg_compacto_sac.png",
            mime="image/png"
        )
