import os
import re
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
import yt_dlp
import requests

app = FastAPI(
    title="Azannas Music Engine API",
    description="Motor de busca, extração e streaming sem anúncios (Direct Alexa Stream Engine v9.0.0)",
    version="9.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FAST_YTDL_ARGS = {
    'youtube': {
        'player_client': ['android', 'web']
    }
}

def get_ytdl_search_opts(limit: int = 15):
    return {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'extract_flat': 'in_playlist',
        'quiet': True,
        'no_warnings': True,
        'default_search': f'ytsearch{limit}',
        'extractor_args': FAST_YTDL_ARGS,
    }

def get_ytdl_extract_opts():
    return {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'extractor_args': FAST_YTDL_ARGS,
    }

def parse_tracks(results):
    tracks = []
    if results and 'entries' in results:
        for entry in results['entries']:
            if not entry:
                continue
            track_id = entry.get("id")
            # Only accept valid YouTube video IDs (11 characters)
            if not track_id or len(track_id) != 11 or track_id.startswith(("UC", "PL")):
                continue
            tracks.append({
                "id": track_id,
                "title": entry.get("title", "Sem Título"),
                "artist": entry.get("uploader", "Artista Desconhecido"),
                "duration": entry.get("duration", 0),
                "thumbnail_url": entry.get("thumbnails", [{}])[-1].get("url") if entry.get("thumbnails") else f"https://i.ytimg.com/vi/{track_id}/hqdefault.jpg"
            })
    return tracks

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "app": "Azannas Music Engine",
        "mode": "direct_alexa_fast_redirect",
        "version": "9.0.0"
    }

@app.get("/version")
def version_check():
    return {
        "version": "9.0.0",
        "mode": "direct_alexa_fast_redirect"
    }

@app.get("/mode")
def get_engine_mode():
    return {"mode": "direct_alexa_fast_redirect", "description": "Redirecionamento Ultrarrápido HTTP 307 para Alexa Echo"}

@app.get("/search")
def search_tracks(q: str = Query(..., description="Termo de busca")):
    try:
        opts = get_ytdl_search_opts(limit=15)
        with yt_dlp.YoutubeDL(opts) as ydl:
            results = ydl.extract_info(f"ytsearch15:{q}", download=False)
            tracks = parse_tracks(results)
            return {"query": q, "results": tracks, "mode": "direct_alexa_fast_redirect"}
    except Exception as e:
        print("Search error:", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stream/{track_id}")
def get_stream_url(track_id: str):
    try:
        opts = get_ytdl_extract_opts()
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"https://www.youtube.com/watch?v={track_id}", download=False)
            if res:
                stream_url = res.get("url")
                if stream_url:
                    return {
                        "id": track_id,
                        "title": res.get("title"),
                        "artist": res.get("uploader"),
                        "duration": res.get("duration"),
                        "thumbnail_url": res.get("thumbnail") or f"https://i.ytimg.com/vi/{track_id}/hqdefault.jpg",
                        "stream_url": stream_url,
                        "mode": "direct_fast"
                    }
        raise HTTPException(status_code=404, detail="Stream não localizado.")
    except Exception as e:
        print("Stream extract error:", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download/{track_id}")
def proxy_download(track_id: str, request: Request):
    try:
        opts = get_ytdl_extract_opts()
        direct_audio_url = None
        ytdl_headers = {}
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"https://www.youtube.com/watch?v={track_id}", download=False)
            if res:
                direct_audio_url = res.get("url")
                ytdl_headers = res.get("http_headers", {})

        if not direct_audio_url:
            raise HTTPException(status_code=404, detail="Áudio não encontrado.")
        
        range_header = request.headers.get("range")
        if range_header:
            ytdl_headers['Range'] = range_header

        resp = requests.get(direct_audio_url, headers=ytdl_headers, stream=True, timeout=25)
        
        def iterfile():
            for chunk in resp.iter_content(chunk_size=16384):
                yield chunk

        response_headers = {
            'Content-Disposition': f'attachment; filename="{track_id}.m4a"',
            'Content-Type': 'audio/mp4',
            'Accept-Ranges': 'bytes',
        }

        content_length = resp.headers.get('content-length')
        if content_length:
            response_headers['Content-Length'] = content_length

        content_range = resp.headers.get('content-range')
        if content_range:
            response_headers['Content-Range'] = content_range

        return StreamingResponse(
            iterfile(),
            status_code=resp.status_code,
            headers=response_headers,
            media_type='audio/mp4'
        )
    except Exception as e:
        print(f"Download Error for {track_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def clean_track_title(title: str) -> str:
    cleaned = re.sub(r'[\(\[\{].*?[\)\]\}]', '', title)
    cleaned = re.sub(r'\b(official|video|lyric|lyrics|audio|hd|4k|remastered|version|clipe|oficial|ao vivo|live)\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

@app.get("/lyrics")
def get_lyrics(query: str = "", artist: str = "", title: str = ""):
    try:
        clean_artist = artist.strip() if artist and artist.strip().lower() not in ["artista desconhecido", "youtube", "vevo", "unknown artist", "none", "null"] else ""
        clean_t = clean_track_title(title) if title else ""
        
        if clean_artist and clean_t:
            search_query = f"{clean_artist} {clean_t}"
        elif clean_t:
            search_query = clean_track_title(query)
        elif query:
            search_query = clean_track_title(query)
        else:
            search_query = ""

        if not search_query:
            return {"status": "not_found", "message": "Consulta vazia."}

        url = f"https://lrclib.net/api/search?q={requests.utils.quote(search_query)}"
        resp = requests.get(url, headers={"User-Agent": "AzannasMusic/1.0"}, timeout=6)
        
        if resp.status_code == 200:
            results = resp.json()
            if results and isinstance(results, list) and len(results) > 0:
                best = next((x for x in results if x.get("syncedLyrics")), results[0])
                return {
                    "status": "ok",
                    "id": best.get("id"),
                    "track_name": best.get("trackName"),
                    "artist_name": best.get("artistName"),
                    "synced_lyrics": best.get("syncedLyrics"),
                    "plain_lyrics": best.get("plainLyrics"),
                }
        return {"status": "not_found", "message": "Letra não encontrada."}
    except Exception as e:
        print("Lyrics search error:", e)
        return {"status": "error", "detail": str(e)}

@app.get("/alexa-stream/{track_id}")
def alexa_stream_proxy(track_id: str, request: Request):
    """Redireciona a Alexa diretamente para o CDN de alta velocidade do YouTube (googlevideo.com) em <2.5s."""
    try:
        opts = get_ytdl_extract_opts()
        direct_audio_url = None

        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"https://www.youtube.com/watch?v={track_id}", download=False)
            if res:
                direct_audio_url = res.get("url")

        if not direct_audio_url:
            raise HTTPException(status_code=404, detail="Audio stream não localizado.")

        return RedirectResponse(url=direct_audio_url, status_code=307)
    except Exception as e:
        print(f"Alexa Stream Redirect Error for {track_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/alexa")
async def alexa_webhook(request: Request):
    """Alexa Custom Skill Webhook com resposta ultrarrápida (<1.5s) e redirecionamento de streaming."""
    try:
        body = await request.json()
        req_data = body.get("request", {})
        req_type = req_data.get("type", "")

        if req_type == "LaunchRequest":
            return {
                "version": "1.0",
                "response": {
                    "outputSpeech": {
                        "type": "PlainText",
                        "text": "Bem-vindo ao Azannas Music! Qual música ou artista você deseja ouvir?"
                    },
                    "shouldEndSession": False
                }
            }

        if req_type == "IntentRequest":
            intent = req_data.get("intent", {})
            intent_name = intent.get("name", "")

            if intent_name in ["PlayMusicIntent", "SearchAndPlayIntent"]:
                slots = intent.get("slots", {})
                query_slot = slots.get("query", {}) or slots.get("song", {}) or slots.get("artist", {})
                search_term = query_slot.get("value", "").strip()

                if not search_term:
                    return {
                        "version": "1.0",
                        "response": {
                            "outputSpeech": {
                                "type": "PlainText",
                                "text": "Por favor, diga o nome da música ou artista que deseja ouvir."
                            },
                            "shouldEndSession": False
                        }
                    }

                # Step 1: Flat search para obter ID do vídeo filtrado de 11 caracteres (<1.5s)
                search_opts = get_ytdl_search_opts(limit=5)
                best_track_id = None
                title = search_term
                artist = "Azannas Music"
                thumb = None

                with yt_dlp.YoutubeDL(search_opts) as ydl:
                    search_res = ydl.extract_info(f"ytsearch5:{search_term}", download=False)
                    tracks = parse_tracks(search_res)
                    if tracks:
                        best = tracks[0]
                        best_track_id = best.get("id")
                        title = best.get("title", search_term)
                        artist = best.get("artist", "Azannas Music")
                        thumb = best.get("thumbnail_url")

                if not best_track_id:
                    return {
                        "version": "1.0",
                        "response": {
                            "outputSpeech": {
                                "type": "PlainText",
                                "text": f"Desculpe, não encontrei a música {search_term} no Azannas Music."
                            },
                            "shouldEndSession": True
                        }
                    }

                # Endpoint de streaming com redirecionamento direto para Alexa (HTTP 307 para googlevideo)
                stream_url = f"https://azannas-music-app.onrender.com/alexa-stream/{best_track_id}"

                if not thumb:
                    thumb = f"https://i.ytimg.com/vi/{best_track_id}/hqdefault.jpg"

                return {
                    "version": "1.0",
                    "response": {
                        "outputSpeech": {
                            "type": "PlainText",
                            "text": f"Tocando {title} no Azannas Music."
                        },
                        "directives": [
                            {
                                "type": "AudioPlayer.Play",
                                "playBehavior": "REPLACE_ALL",
                                "audioItem": {
                                    "stream": {
                                        "token": best_track_id,
                                        "url": stream_url,
                                        "offsetInMilliseconds": 0
                                    },
                                    "metadata": {
                                        "title": title,
                                        "subtitle": artist,
                                        "art": {
                                            "sources": [{"url": thumb}]
                                        }
                                    }
                                }
                            }
                        ],
                        "shouldEndSession": True
                    }
                }

            elif intent_name in ["AMAZON.PauseIntent", "AMAZON.StopIntent", "AMAZON.CancelIntent"]:
                return {
                    "version": "1.0",
                    "response": {
                        "directives": [
                            {
                                "type": "AudioPlayer.Stop"
                            }
                        ],
                        "shouldEndSession": True
                    }
                }

            elif intent_name == "AMAZON.HelpIntent":
                return {
                    "version": "1.0",
                    "response": {
                        "outputSpeech": {
                            "type": "PlainText",
                            "text": "Você pode pedir para tocar qualquer música ou artista na sua caixinha. Por exemplo: fale, Alexa, tocar Legião Urbana na minha caixinha."
                        },
                        "shouldEndSession": False
                    }
                }

        if req_type.startswith("AudioPlayer."):
            return {
                "version": "1.0",
                "response": {}
            }

        return {
            "version": "1.0",
            "response": {
                "shouldEndSession": True
            }
        }
    except Exception as e:
        print("Alexa webhook error:", e)
        return {
            "version": "1.0",
            "response": {
                "outputSpeech": {
                    "type": "PlainText",
                    "text": "Ocorreu um erro ao processar seu pedido no Azannas Music."
                },
                "shouldEndSession": True
            }
        }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
