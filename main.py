import os
import re
import base64
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import yt_dlp
import requests

app = FastAPI(
    title="Azannas Music Engine API",
    description="Motor de busca, extração e streaming sem anúncios (Direct InnerTube Engine)",
    version="3.5.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

COOKIE_PATH = os.path.join(os.path.dirname(__file__), "cookies.txt")

# Check if Base64 encoded cookies are passed via environment variable
COOKIES_B64 = os.environ.get("COOKIES_B64")
if COOKIES_B64:
    try:
        decoded_cookies = base64.b64decode(COOKIES_B64).decode("utf-8")
        with open(COOKIE_PATH, "w", encoding="utf-8") as f:
            f.write(decoded_cookies)
        print("Successfully loaded cookies.txt from COOKIES_B64 environment variable.")
    except Exception as e:
        print(f"Error decoding COOKIES_B64: {e}")

HAS_COOKIES = os.path.exists(COOKIE_PATH)

CHROME_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

# InnerTube Android/iOS client configuration for fast extraction without proxy/webpage blocking
FAST_YTDL_ARGS = {
    'youtube': {
        'player_client': ['android', 'ios'],
        'player_skip': ['webpage', 'configs']
    }
}

def get_ytdl_search_opts(limit: int = 15):
    opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'extract_flat': 'in_playlist',
        'quiet': True,
        'no_warnings': True,
        'default_search': f'ytsearch{limit}',
        'http_headers': CHROME_HEADERS,
        'extractor_args': FAST_YTDL_ARGS,
    }
    if HAS_COOKIES:
        opts['cookiefile'] = COOKIE_PATH
    return opts

def get_ytdl_extract_opts():
    opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'http_headers': CHROME_HEADERS,
        'extractor_args': FAST_YTDL_ARGS,
    }
    if HAS_COOKIES:
        opts['cookiefile'] = COOKIE_PATH
    return opts

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
        "has_cookies": HAS_COOKIES,
        "mode": "direct_innertube",
        "version": "3.5.0"
    }

@app.get("/version")
def version_check():
    return {
        "version": "3.5.0",
        "has_cookies": HAS_COOKIES,
        "mode": "direct_innertube"
    }

@app.get("/mode")
def get_engine_mode():
    return {"mode": "direct_innertube", "description": "Conexão Direta Otimizada via InnerTube Android/iOS"}

@app.get("/search")
def search_tracks(q: str = Query(..., description="Termo de busca")):
    try:
        opts = get_ytdl_search_opts(limit=15)
        with yt_dlp.YoutubeDL(opts) as ydl:
            results = ydl.extract_info(f"ytsearch15:{q}", download=False)
            tracks = parse_tracks(results)
            return {"query": q, "results": tracks, "mode": "direct_innertube"}
    except Exception as e:
        print("Search error:", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stream/{track_id}")
def get_stream_url(track_id: str):
    url = f"https://www.youtube.com/watch?v={track_id}"
    try:
        opts = get_ytdl_extract_opts()
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            stream_url = info.get("url")
            if not stream_url:
                raise HTTPException(status_code=404, detail="Stream não localizado.")
            return {
                "id": track_id,
                "title": info.get("title"),
                "artist": info.get("uploader"),
                "duration": info.get("duration"),
                "thumbnail_url": info.get("thumbnail"),
                "stream_url": stream_url,
                "mode": "direct_innertube"
            }
    except Exception as e:
        print("Stream extract error:", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download/{track_id}")
def proxy_download(track_id: str, request: Request):
    try:
        url = f"https://www.youtube.com/watch?v={track_id}"
        opts = get_ytdl_extract_opts()
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            direct_audio_url = info.get("url")
            ytdl_headers = info.get("http_headers", CHROME_HEADERS)

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
            search_query = clean_t
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
    """Proxy de áudio otimizado especificamente para Amazon Alexa AudioPlayer (inline streaming sem attachment)."""
    try:
        url = f"https://www.youtube.com/watch?v={track_id}"
        opts = get_ytdl_extract_opts()
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            direct_audio_url = info.get("url")
            ytdl_headers = info.get("http_headers", CHROME_HEADERS)

        if not direct_audio_url:
            raise HTTPException(status_code=404, detail="Audio stream não localizado.")

        range_header = request.headers.get("range")
        if range_header:
            ytdl_headers['Range'] = range_header

        resp = requests.get(direct_audio_url, headers=ytdl_headers, stream=True, timeout=25)

        def iterfile():
            for chunk in resp.iter_content(chunk_size=16384):
                yield chunk

        response_headers = {
            'Content-Type': 'audio/mp4',
            'Accept-Ranges': 'bytes',
            'Cache-Control': 'no-cache',
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
        print(f"Alexa Stream Proxy Error for {track_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/alexa")
async def alexa_webhook(request: Request):
    """Alexa Custom Skill Webhook com resposta direta do InnerTube CDN."""
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

                # Step 1: Buscar a melhor faixa (ytsearch5)
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

                # Step 2: Extrair a URL direta de streaming (googlevideo.com) via InnerTube Android/iOS
                direct_audio_url = None
                try:
                    extract_opts = get_ytdl_extract_opts()
                    with yt_dlp.YoutubeDL(extract_opts) as ydl:
                        info = ydl.extract_info(f"https://www.youtube.com/watch?v={best_track_id}", download=False)
                        direct_audio_url = info.get("url")
                except Exception as ex_extract:
                    print(f"Direct stream extract failed for Alexa ({best_track_id}):", ex_extract)

                # Fallback se a extração de URL falhar
                if not direct_audio_url:
                    direct_audio_url = f"https://azannas-music-app.onrender.com/download/{best_track_id}"

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
                                        "url": direct_audio_url,
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
