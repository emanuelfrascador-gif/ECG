import json
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

def generar_prompt_blindado():
    """
    Genera el prompt maestro diseñado para obligar al modelo a realizar un análisis
    sistemático, exhaustivo y estructurado, sin margen para alucinaciones en el reporte.
    """
    return """
    ERES UN CARDIÓLOGO CLÍNICO EXPERTO DE MÁXIMA PRECISIÓN. Tu análisis de este ECG debe ser perfecto, ya que decisiones vitales dependen de él.
    
    INSTRUCCIONES DE ANÁLISIS (OBLIGATORIO):
    1. BARRIDO SISTEMÁTICO: Analiza derivación por derivación, onda por onda (P, QRS, T, U), segmentos (ST, PR) e intervalos (QT, PR). Correlaciona los hallazgos entre sí.
    2. CAPTURA TOTAL: Identifica ABSOLUTAMENTE TODO lo que salga del ritmo sinusal normal, desde lo más grave hasta lo más mínimo.
    3. TRIPLE COMPROBACIÓN: Una vez encontrada una alteración, compruébala nuevamente. Si es real, búscale su imagen en espejo en las derivaciones correspondientes.
    4. ETIOLOGÍA EXHAUSTIVA: Basada en manuales de cardiología. Analiza diagnósticos diferenciales con razonamiento crítico. Los datos del paciente son complementarios al ECG.
    5. TRATAMIENTO ESTRICTO: El tratamiento farmacológico debe estar COMPLETO. Especifica siempre FÁRMACO y DOSIS. Nunca pongas solo el grupo terapéutico ni el fármaco sin dosis.
    
    FORMATO DE SALIDA (ESTRICTAMENTE JSON):
    {
      "hallazgos_clinicos": ["lista", "de", "hallazgos"],
      "etiologia": ["lista", "exhaustiva", "de", "causas"],
      "criterios_utilizados": {
        "evaluados": ["criterios que se buscaron en el ECG (ej. Sokolow-Lyon, Wellens)"],
        "confirmados": ["criterios que dieron positivo"],
        "descartados": ["criterios que se buscaron pero dieron negativo"]
      },
      "tratamiento_y_conducta": ["lista de indicaciones", "FÁRMACO X - DOSIS Y mg/dia"],
      "marcadores_ecg": [
        {
          "alteracion": "Nombre exacto de la alteración (ej. Inversión onda T)",
          "color_hex": "#FF0000",
          "coordenadas_caja": [x, y, ancho, alto]
        }
      ],
      "flechas_espejo": [
        {
          "origen": [x1, y1],
          "destino": [x2, y2],
          "descripcion": "Correlación cara inferior con cara lateral alta"
        }
      ]
    }
    """

def procesar_y_dibujar_ecg(imagen_path, json_respuesta):
    """
    Procesa la imagen del ECG dibujando las marcas y flechas, y asegura que 
    la leyenda sea una representación 1:1 exacta de lo que se ha dibujado.
    """
    # 1. Cargar imagen con OpenCV
    img = cv2.imread(imagen_path)
    if img is None:
        raise ValueError("No se pudo cargar la imagen del ECG.")
    
    leyenda_generada = []

    # 2. Dibujar marcadores de alteraciones (Cajas/Círculos)
    for marcador in json_respuesta.get("marcadores_ecg", []):
        x, y, w, h = marcador["coordenadas_caja"]
        color_hex = marcador["color_hex"]
        # Convertir HEX a BGR para OpenCV
        color_bgr = tuple(int(color_hex.lstrip('#')[i:i+2], 16) for i in (4, 2, 0))
        
        # Dibujar rectángulo semitransparente o contorno
        cv2.rectangle(img, (x, y), (x+w, y+h), color_bgr, 2)
        
        # Guardar estrictamente lo que se dibujó para la leyenda
        if marcador["alteracion"] not in [item["texto"] for item in leyenda_generada]:
            leyenda_generada.append({
                "color_bgr": color_bgr,
                "texto": marcador["alteracion"]
            })

    # 3. Dibujar flechas finas negras para alteraciones en espejo
    # OpenCV usa grosor 1 para líneas finas y color (0,0,0) para negro
    for flecha in json_respuesta.get("flechas_espejo", []):
        pt1 = tuple(flecha["origen"])
        pt2 = tuple(flecha["destino"])
        
        cv2.arrowedLine(
            img, 
            pt1, 
            pt2, 
            (0, 0, 0), # Negro
            thickness=1, # Fina
            tipLength=0.03 # Tamaño de la punta
        )

    # Convertir a PIL para añadir textos y reporte (más fácil manejo tipográfico)
    img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    
    # Aquí puedes integrar tu código existente de ImageFont
    # font = ImageFont.truetype("arial.ttf", 14)
    
    # 4. Construir Leyenda Estricta (1:1 con las marcas)
    # Ejemplo conceptual de cómo plasmarla:
    y_offset = img.shape[0] - 100 # Posición inferior
    draw.text((20, y_offset - 20), "LEYENDA ESTRICTA (Marcas en imagen):", fill=(0,0,0))
    for item in leyenda_generada:
        # Dibujar punto de color y texto al lado
        color_rgb = (item["color_bgr"][2], item["color_bgr"][1], item["color_bgr"][0])
        draw.ellipse([20, y_offset, 30, y_offset+10], fill=color_rgb)
        draw.text((40, y_offset), item["texto"], fill=(0,0,0))
        y_offset += 20
        
    return img_pil, json_respuesta

# --- EJEMPLO DE USO ---
# En tu flujo, reemplazas la llamada al LLM para que use 'generar_prompt_blindado()'
# json_del_modelo = llamar_a_tu_llm(imagen, generar_prompt_blindado())
# img_final, datos_validados = procesar_y_dibujar_ecg("ecg_paciente.png", json_del_modelo)
# img_final.save("informe_ecg_profesional.png")
