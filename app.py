import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import io

st.set_page_config(page_title="Analizador ECG SAC", layout="wide")

st.title("⚡ Analizador ECG SAC - Panel Clínico Integrado")
st.write("Sube tu tira de ECG en formato JPG o PNG para generar el panel compacto sin espacios blancos.")

uploaded_file = st.file_uploader("Seleccionar archivo de ECG", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    # Cargar imagen
    ecg_orig = Image.open(uploaded_file).convert("RGB")
    w_orig, h_orig = ecg_orig.size

    # Definir panel de análisis compacto
    ancho_panel = 1350
    alto_final = h_orig
    imagen_final = Image.new("RGB", (w_orig + ancho_panel, alto_final), color=(255, 255, 255))
    imagen_final.paste(ecg_orig, (0, 0))

    capa_overlay = Image.new("RGBA", (w_orig + ancho_panel, alto_final), (255, 255, 255, 0))
    draw_overlay = ImageDraw.Draw(capa_overlay)

    # Datos clínicos dinámicos de ejemplo (diseño compacto)
    analisis_hallazgos = {
        "datos_tecnicos": "Calibracion estandar 25 mm/s, 10 mm/mV | Ritmo Sinusal con ectopia.",
        "lista_hallazgos": [
            "Trastorno de conduccion intraventricular derecho.",
            "Criterios de alto voltaje compatibles con HVI.",
            "Alteraciones morfologicas de la onda P (auricular).",
            "Presencia de extrasistoles ventriculares (ESV) aisladas.",
            "Modificaciones secundarias en repolarizacion."
        ],
        "leyenda": [
            ((178, 60, 60), "HVI: Derivadas V2 (S) y V5 (R).", "Sv2+Rv5 <= 35mm"),
            ((50, 120, 200), "Conduccion: QRS ancho en V1-V2.", "QRS < 0.12 s"),
            ((200, 160, 30), "Auricular: Onda P en V1/Frontales.", "Duracion < 0.11 s"),
            ((50, 160, 50), "Repolarizacion: ST/T en V4-V6.", "ST isoelectrico"),
            ((200, 30, 200), "Ectopia: Complejos prematuros.", "RR constante")
        ],
        "etiologia": "Compatible con HTA cronica y sobrecarga de presion.",
        "mini_ionograma": {
            "K_estimado": "Normokalemia (ausencia de T picudas simetricas).",
            "Ca_estimado": "Intervalo QT adaptado a frecuencia, sin alteraciones."
        },
        "manejo_sac": (
            "1. Control de Presion Arterial:\n"
            "   • (Pendiente de analisis IA)\n"
            "2. Proteccion Cardioprotectora:\n"
            "   • (Pendiente de analisis IA)\n"
            "3. Inhibidores SGLT2 / Moduladores IC:\n"
            "   • (Pendiente de analisis IA)\n"
            "4. Estudios Complementarios:\n"
            "   • (Pendiente de analisis IA)"
        )
    }

    # Dibujado compacto en el panel
    draw = ImageDraw.Draw(imagen_final)
    try:
        f_titulo = ImageFont.truetype("DejaVuSans-Bold.ttf", 20)
        f_sub = ImageFont.truetype("DejaVuSans-Bold.ttf", 12)
        f_texto = ImageFont.truetype("DejaVuSans.ttf", 11)
        f_rojo = ImageFont.truetype("DejaVuSans-Bold.ttf", 11)
    except:
        f_titulo = f_sub = f_texto = f_rojo = ImageFont.load_default()

    col1_x = w_orig + 25
    col2_x = w_orig + 680
    margen_sup = 20
    espacio_bloque = 16 
    espacio_item = 14

    draw.line([(w_orig, 0), (w_orig, alto_final)], fill=(180, 180, 180), width=2)
    draw.text((col1_x, margen_sup), "RESEÑA CARDIOLÓGICA PROFUNDA Y MANEJO CLÍNICO (GUÍAS SAC)", fill=(10, 40, 90), font=f_titulo)
    draw.line([(col1_x, margen_sup + 25), (w_orig + ancho_panel - 25, margen_sup + 25)], fill=(200, 200, 200), width=1)

    def dibujar_bloque_compacto(x, y, titulo_bloque, lineas, es_lista=False):
        draw.text((x, y), titulo_bloque, fill=(10, 40, 80), font=f_sub)
        y += espacio_bloque + 4 
        if es_lista:
            for idx, item in enumerate(lineas):
                if isinstance(item, tuple):
                    color_rgb, texto_item, valor_normal = item
                    draw.ellipse([x + 2, y + 2, x + 12, y + 12], fill=color_rgb, outline=color_rgb)
                    draw.text((x + 20, y), texto_item, fill=(30, 30, 30), font=f_texto)
                    draw.text((x + 330, y), f"Normal: {valor_normal}", fill=(200, 30, 30), font=f_rojo)
                else:
                    draw.text((x, y), f"{idx+1}. {item}", fill=(30, 30, 30), font=f_texto)
                y += espacio_item
        else:
            for item in lineas:
                draw.text((x, y), item, fill=(30, 30, 30), font=f_texto)
                y += espacio_item
        return y + (espacio_bloque / 2)

    # Columnas
    y_c1 = margen_sup + 45
    y_c1 = dibujar_bloque_compacto(col1_x, y_c1, "DATOS TECNICOS Y HALLAZGOS CLAVE:", [analisis_hallazgos["datos_tecnicos"]] + analisis_hallazgos["lista_hallazgos"])
    y_c1 = dibujar_bloque_compacto(col1_x, y_c1, "LEYENDA DE COLORES Y PARAMETROS NORMALES:", analisis_hallazgos["leyenda"], es_lista=True)

    y_c2 = margen_sup + 45
    y_c2 = dibujar_bloque_compacto(col2_x, y_c2, "ETIOLOGIA Y CORRELACION CLINICA:", [analisis_hallazgos["etiologia"]])
    y_c2 = dibujar_bloque_compacto(col2_x, y_c2, "MINI-IONOGRAMA ELECTROCARDIOGRAFICO:", 
                                    [f"• K+ Estimado: {analisis_hallazgos['mini_ionograma']['K_estimado']}",
                                     f"• Ca2+ Estimado: {analisis_hallazgos['mini_ionograma']['Ca_estimado']}"])
    y_c2 = dibujar_bloque_compacto(col2_x, y_c2, "MANEJO CLINICO Y FARMACOS (GUIAS SAC):", analisis_hallazgos["manejo_sac"].split('\n'))

    # Marcar sobre el ECG
    puntos_marcar = [
        (int(w_orig * 0.63), int(h_orig * 0.73), (178, 60, 60, 100)),
        (int(w_orig * 0.93), int(h_orig * 0.74), (178, 60, 60, 100)),
        (int(w_orig * 0.33), int(h_orig * 0.17), (50, 120, 200, 100)),
        (int(w_orig * 0.12), int(h_orig * 0.14), (200, 160, 30, 100)),
    ]
    for px, py, rgba in puntos_marcar:
        r = 14
        draw_overlay.ellipse([px-r, py-r, px+r, py+r], fill=rgba, outline=rgba)
    
    imagen_final = Image.alpha_composite(imagen_final.convert("RGBA"), capa_overlay).convert("RGB")

    # Mostrar vista previa
    st.image(imagen_final, caption="Vista previa del resultado integrado", use_container_width=True)

    # Botón de descarga
    buf = io.BytesIO()
    imagen_final.save(buf, format="PNG", compress_level=0)
    byte_im = buf.getvalue()

    st.download_button(
        label="📥 Descargar Imagen Final en Alta Calidad",
        data=byte_im,
        file_name="ecg_analisis_final.png",
        mime="image/png"
    )
