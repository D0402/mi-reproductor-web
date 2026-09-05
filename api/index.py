import os
import urllib.request
import urllib.parse
import json
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import psycopg2
# Carga las variables locales si existe el archivo, sino las toma de Vercel
load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")

# Asegúrate de que tu aplicación se llame 'app' (Vercel busca esta variable)
app = FastAPI()

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def inicializar_bd():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS canciones (
                id SERIAL PRIMARY KEY,
                video_id VARCHAR(50) NOT NULL,
                titulo VARCHAR(255) DEFAULT 'Canción de YouTube'
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print("Error inicializando BD:", e)

inicializar_bd()

def extraer_video_id(url: str) -> str:
    url_limpia = url.split('&list=')[0].split('&pp=')[0]
    regex = r"(?:v=|\/([0-9A-Za-z_-]{11}).*|youtu\.be\/|embed\/)([0-9A-Za-z_-]{11})"
    match = re.search(regex, url_limpia)
    if match:
        return match.group(2) if match.group(2) else match.group(1)
    if "watch?v=" in url_limpia:
        vid_id = url_limpia.split("watch?v=")[1][:11]
        if len(vid_id) == 11:
            return vid_id
    raise ValueError("URL inválida de YouTube")

# Hacemos los campos opcionales para recibir Links o IDs directamente
class CancionRequest(BaseModel):
    url: Optional[str] = None
    video_id: Optional[str] = None
    titulo: Optional[str] = None

@app.get("/api/buscar")
def buscar_canciones(q: str):
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise HTTPException(status_code=500, detail="Falta API KEY")
    try:
        query = urllib.parse.quote(q)
        url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&maxResults=5&q={query}&type=video&key={key}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            
        resultados = []
        for item in data.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            if video_id:
                resultados.append({
                    "video_id": video_id,
                    "titulo": item.get("snippet", {}).get("title", "Sin título"),
                    "canal": item.get("snippet", {}).get("channelTitle", "Desconocido"),
                    "miniatura": item.get("snippet", {}).get("thumbnails", {}).get("default", {}).get("url", "")
                })
        return resultados
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/canciones")
def obtener_canciones():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, video_id, titulo FROM canciones ORDER BY id DESC;")
        filas = cur.fetchall()
        cur.close()
        conn.close()
        return [{"id": f[0], "video_id": f[1], "titulo": f[2]} for f in filas]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/canciones")
def agregar_cancion(req: CancionRequest):
    try:
        video_id = req.video_id
        titulo_final = req.titulo

        # Si el usuario pegó un link directo
        if not video_id:
            if not req.url:
                raise ValueError("Se requiere URL o video_id")
            video_id = extraer_video_id(req.url)

        # Si no hay título, intentamos buscarlo
        if not titulo_final:
            titulo_final = f"Video ({video_id})"
            key = os.environ.get("YOUTUBE_API_KEY")
            if key:
                try:
                    url_details = f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={video_id}&key={key}"
                    req_api = urllib.request.Request(url_details, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req_api) as resp:
                        data = json.loads(resp.read().decode())
                        if data.get("items"):
                            titulo_final = data["items"][0]["snippet"]["title"]
                except Exception:
                    pass

        # Construimos la URL falsa/real para satisfacer tu base de datos
        url_reconstruida = f"https://www.youtube.com/watch?v={video_id}"

        # Guardar en BD (Añadimos 'url' al INSERT)
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO canciones (url, video_id, titulo) VALUES (%s, %s, %s) RETURNING id;", 
            (url_reconstruida, video_id, titulo_final)
        )
        nuevo_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        
        return {"id": nuevo_id, "video_id": video_id, "titulo": titulo_final}
    except Exception as e:
        print("Error en POST /canciones:", str(e))
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/canciones/{cancion_id}")
def eliminar_cancion(cancion_id: int):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM canciones WHERE id = %s;", (cancion_id,))
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


handler = Mangum(app)