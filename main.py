import os
import re
import base64
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
import yt_dlp
import requests

app = FastAPI(
    title="Azannas Music Engine API",
    description="Motor de busca, extração e streaming sem anúncios (AllanProxies BR Engine v10.1.0)",
    version="10.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RESIDENTIAL_PROXY_URL = "http://fed63918541e5361b7c1:13e29a40e6a9106d@sv1.allanproxys.com:824"
HAS_PROXY = True

CHROME_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

FAST_YTDL_ARGS = {
    'youtube': {
        'player_client': ['android', 'android_embedded', 'tv_embedded']
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
    if HAS_PROXY:
        opts['proxy'] = RESIDENTIAL_PROXY_URL
    return opts

def get_ytdl_extract_opts():
    opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'http_headers': CHROME_HEADERS,
        'extractor_args': FAST_YTDL_ARGS,
    }
    if HAS_PROXY:
        opts['proxy'] = RESIDENTIAL_PROXY_URL
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
        "has_proxy": HAS_PROXY,
        "mode": "proxy" if HAS_PROXY else "fallback",
        "version": "10.0.0"
    }

@app.get("/version")
def version_check():
    return {
        "version": "10.0.0",
        "mode": "proxy" if HAS_PROXY else "fallback",
        "has_proxy": HAS_PROXY
    }

@app.get("/mode")
def get_engine_mode():
    if HAS_PROXY:
        return {"mode": "proxy", "description": "Conectado via Proxy Residencial BR (AllanProxies - Luz Azul Neon)"}
    return {"mode": "fallback", "description": "Conexão Direta (Luz Amarela Neon)"}

@app.get("/search")
def search_tracks(q: str = Query(..., description="Termo de busca")):
    try:
        opts = get_ytdl_search_opts(limit=15)
        with yt_dlp.YoutubeDL(opts) as ydl:
            results = ydl.extract_info(f"ytsearch15:{q}", download=False)
            tracks = parse_tracks(results)
            return {"query": q, "results": tracks, "mode": "proxy" if HAS_PROXY else "fallback"}
    except Exception as e:
        print("Search error:", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stream/{track_id}")
def get_stream_url(track_id: str):
    try:
        opts = get_ytdl_extract_opts()
        url = f"https://www.youtube.com/watch?v={track_id}"
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(url, download=False)
            if res and res.get("url"):
                return {
                    "id": track_id,
                    "title": res.get("title"),
                    "artist": res.get("uploader"),
                    "duration": res.get("duration"),
                    "thumbnail_url": res.get("thumbnail") or f"https://i.ytimg.com/vi/{track_id}/hqdefault.jpg",
                    "stream_url": res.get("url"),
                    "mode": "proxy" if HAS_PROXY else "fallback"
                }
        raise HTTPException(status_code=404, detail="Stream não localizado.")
    except Exception as e:
        print("Stream extract error:", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download/{track_id}")
def proxy_download(track_id: str, request: Request):
    try:
        opts = get_ytdl_extract_opts()
        url = f"https://www.youtube.com/watch?v={track_id}"
        direct_audio_url = None
        ytdl_headers = {}
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(url, download=False)
            if res and res.get("url"):
                direct_audio_url = res.get("url")
                ytdl_headers = res.get("http_headers", CHROME_HEADERS)

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

alexa_sessions = {}

def get_alexa_device_id(body: dict) -> str:
    """Extrai o ID único do dispositivo ou usuário da Alexa."""
    context = body.get("context", {})
    device_id = context.get("System", {}).get("device", {}).get("deviceId")
    if not device_id:
        device_id = context.get("System", {}).get("user", {}).get("userId", "default_alexa_device")
    return device_id

def create_alexa_stream_response(track: dict, play_behavior: str = "REPLACE_ALL", speech_text: str = None, expected_prev_token: str = None, offset_ms: int = 0):
    """Gera uma resposta padronizada da API AudioPlayer da Alexa."""
    track_id = track.get("id")
    title = track.get("title", "Música")
    artist = track.get("artist", "Azannas Music")
    thumb = track.get("thumbnail_url") or f"https://i.ytimg.com/vi/{track_id}/hqdefault.jpg"
    stream_url = f"https://azannas-music-app.onrender.com/alexa-stream/{track_id}"
    token = f"{track_id}___{offset_ms}"

    stream_data = {
        "token": token,
        "url": stream_url,
        "offsetInMilliseconds": offset_ms
    }
    if expected_prev_token and play_behavior == "ENQUEUE":
        stream_data["expectedPreviousToken"] = expected_prev_token

    directive = {
        "type": "AudioPlayer.Play",
        "playBehavior": play_behavior,
        "audioItem": {
            "stream": stream_data,
            "metadata": {
                "title": title,
                "subtitle": artist,
                "art": {
                    "sources": [{"url": thumb}]
                }
            }
        }
    }

    res_body = {"directives": [directive]}
    if speech_text and play_behavior != "ENQUEUE":
        res_body["outputSpeech"] = {
            "type": "PlainText",
            "text": speech_text
        }
        res_body["shouldEndSession"] = True

    return {
        "version": "1.0",
        "response": res_body
    }

def fetch_tracks_for_alexa_radio(query: str, limit: int = 15):
    """Busca faixas relevantes para gerar a fila do modo rádio da Alexa."""
    opts = get_ytdl_search_opts(limit=limit)
    with yt_dlp.YoutubeDL(opts) as ydl:
        res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        return parse_tracks(res)

@app.get("/alexa-stream/{track_id}")
def alexa_stream_proxy(track_id: str, request: Request):
    """Redireciona a Alexa diretamente para o CDN do YouTube (googlevideo.com)."""
    try:
        opts = get_ytdl_extract_opts()
        url = f"https://www.youtube.com/watch?v={track_id}"
        direct_audio_url = None

        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(url, download=False)
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
    """Alexa Custom Skill Webhook avançado com suporte a Rádio Infinita, Filas e Controles de Voz."""
    try:
        body = await request.json()
        req_data = body.get("request", {})
        req_type = req_data.get("type", "")
        device_id = get_alexa_device_id(body)

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

                tracks = fetch_tracks_for_alexa_radio(search_term, limit=15)
                if not tracks:
                    return {
                        "version": "1.0",
                        "response": {
                            "outputSpeech": {
                                "type": "PlainText",
                                "text": f"Desculpe, não encontrei faixas para {search_term} no Azannas Music."
                            },
                            "shouldEndSession": True
                        }
                    }

                first_track = tracks[0]
                alexa_sessions[device_id] = {
                    "query": search_term,
                    "queue": tracks,
                    "current_index": 0,
                    "stopped_offset": 0,
                    "stopped_token": f"{first_track['id']}___0"
                }

                title = first_track.get("title", search_term)
                artist = first_track.get("artist", "Azannas Music")
                speech = f"Tocando {title} de {artist} e músicas parecidas no Azannas Music."

                return create_alexa_stream_response(first_track, "REPLACE_ALL", speech_text=speech)

            elif intent_name in ["AMAZON.PauseIntent", "AMAZON.StopIntent", "AMAZON.CancelIntent"]:
                return {
                    "version": "1.0",
                    "response": {
                        "directives": [{"type": "AudioPlayer.Stop"}],
                        "shouldEndSession": True
                    }
                }

            elif intent_name == "AMAZON.ResumeIntent":
                session = alexa_sessions.get(device_id)
                if session and session.get("queue"):
                    curr_idx = session.get("current_index", 0)
                    track = session["queue"][curr_idx]
                    offset = session.get("stopped_offset", 0)
                    return create_alexa_stream_response(track, "REPLACE_ALL", offset_ms=offset)
                return {
                    "version": "1.0",
                    "response": {
                        "outputSpeech": {
                            "type": "PlainText",
                            "text": "Nenhuma música pausada no Azannas Music."
                        },
                        "shouldEndSession": True
                    }
                }

            elif intent_name == "AMAZON.NextIntent":
                session = alexa_sessions.get(device_id)
                if session and session.get("queue"):
                    session["current_index"] += 1
                    if session["current_index"] >= len(session["queue"]):
                        try:
                            more = fetch_tracks_for_alexa_radio(f"{session['query']} radio", limit=10)
                            existing_ids = {t["id"] for t in session["queue"]}
                            new_tracks = [t for t in more if t["id"] not in existing_ids]
                            if new_tracks:
                                session["queue"].extend(new_tracks)
                        except Exception as e:
                            print("NextIntent queue expand error:", e)

                    if session["current_index"] < len(session["queue"]):
                        track = session["queue"][session["current_index"]]
                        session["stopped_offset"] = 0
                        speech = f"Tocando {track.get('title')}."
                        return create_alexa_stream_response(track, "REPLACE_ALL", speech_text=speech)

                return {
                    "version": "1.0",
                    "response": {
                        "outputSpeech": {
                            "type": "PlainText",
                            "text": "Não há próxima música disponível na fila."
                        },
                        "shouldEndSession": True
                    }
                }

            elif intent_name in ["AMAZON.PreviousIntent", "AMAZON.StartOverIntent"]:
                session = alexa_sessions.get(device_id)
                if session and session.get("queue"):
                    if intent_name == "AMAZON.PreviousIntent":
                        session["current_index"] = max(0, session.get("current_index", 0) - 1)
                    track = session["queue"][session["current_index"]]
                    session["stopped_offset"] = 0
                    return create_alexa_stream_response(track, "REPLACE_ALL")
                return {
                    "version": "1.0",
                    "response": {
                        "outputSpeech": {
                            "type": "PlainText",
                            "text": "Não foi possível voltar a música no momento."
                        },
                        "shouldEndSession": True
                    }
                }

            elif intent_name == "WhatIsPlayingIntent":
                session = alexa_sessions.get(device_id)
                if session and session.get("queue"):
                    curr_idx = session.get("current_index", 0)
                    track = session["queue"][curr_idx]
                    title = track.get("title", "Música sem título")
                    artist = track.get("artist", "Artista desconhecido")
                    offset = session.get("stopped_offset", 0)
                    speech = f"Você está ouvindo {title} de {artist} no Azannas Music."
                    return create_alexa_stream_response(track, "REPLACE_ALL", speech_text=speech, offset_ms=offset)
                return {
                    "version": "1.0",
                    "response": {
                        "outputSpeech": {
                            "type": "PlainText",
                            "text": "Nenhuma música está tocando no momento no Azannas Music."
                        },
                        "shouldEndSession": True
                    }
                }

            elif intent_name == "AMAZON.HelpIntent":
                return {
                    "version": "1.0",
                    "response": {
                        "outputSpeech": {
                            "type": "PlainText",
                            "text": "Você pode pedir para tocar qualquer música ou artista no Azannas Music, perguntar qual música está tocando, ou dizer pausar, continuar e próxima."
                        },
                        "shouldEndSession": False
                    }
                }

        # Tratar eventos do AudioPlayer
        if req_type == "AudioPlayer.PlaybackNearlyFinished":
            session = alexa_sessions.get(device_id)
            if session and session.get("queue"):
                curr_idx = session.get("current_index", 0)
                next_idx = curr_idx + 1

                if next_idx >= len(session["queue"]):
                    try:
                        more = fetch_tracks_for_alexa_radio(f"{session['query']} radio", limit=10)
                        existing_ids = {t["id"] for t in session["queue"]}
                        new_tracks = [t for t in more if t["id"] not in existing_ids]
                        if new_tracks:
                            session["queue"].extend(new_tracks)
                    except Exception as e:
                        print("PlaybackNearlyFinished queue expand error:", e)

                if next_idx < len(session["queue"]):
                    curr_track = session["queue"][curr_idx]
                    next_track = session["queue"][next_idx]
                    prev_token = f"{curr_track['id']}___{session.get('stopped_offset', 0)}"
                    return create_alexa_stream_response(next_track, "ENQUEUE", expected_prev_token=prev_token)

        elif req_type == "AudioPlayer.PlaybackStarted":
            token = req_data.get("token", "")
            session = alexa_sessions.get(device_id)
            if session and session.get("queue") and token:
                for idx, t in enumerate(session["queue"]):
                    if t["id"] in token:
                        session["current_index"] = idx
                        break
            return {"version": "1.0", "response": {}}

        elif req_type == "AudioPlayer.PlaybackStopped":
            offset = req_data.get("offsetInMilliseconds", 0)
            token = req_data.get("token", "")
            session = alexa_sessions.get(device_id)
            if session:
                session["stopped_offset"] = offset
                session["stopped_token"] = token
            return {"version": "1.0", "response": {}}

        return {"version": "1.0", "response": {}}
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
