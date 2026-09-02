import os
import base64
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import yt_dlp
import requests

app = FastAPI(
    title="Azannas Music Engine API",
    description="Motor de busca, extração e streaming sem anúncios",
    version="2.3.0"
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

# Check if Residential Proxy URL is configured (e.g., http://user:pass@p.webshare.io:80)
RESIDENTIAL_PROXY_URL = os.environ.get("RESIDENTIAL_PROXY_URL") or os.environ.get("HTTP_PROXY") or os.environ.get("WEB_PROXY")
if RESIDENTIAL_PROXY_URL:
    print("Residential Proxy enabled for yt-dlp.")
else:
    print("No Residential Proxy specified. Running direct connection.")

CHROME_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

def get_ytdl_search_opts():
    opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'extract_flat': 'in_playlist',
        'quiet': True,
        'no_warnings': True,
        'default_search': 'ytsearch15',
        'http_headers': CHROME_HEADERS,
    }
    if HAS_COOKIES:
        opts['cookiefile'] = COOKIE_PATH
    if RESIDENTIAL_PROXY_URL:
        opts['proxy'] = RESIDENTIAL_PROXY_URL
    return opts

def get_ytdl_extract_opts():
    opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'http_headers': CHROME_HEADERS,
    }
    if HAS_COOKIES:
        opts['cookiefile'] = COOKIE_PATH
    if RESIDENTIAL_PROXY_URL:
        opts['proxy'] = RESIDENTIAL_PROXY_URL
    return opts

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "app": "Azannas Music Engine",
        "has_cookies": HAS_COOKIES,
        "has_proxy": bool(RESIDENTIAL_PROXY_URL),
        "version": "2.3.0"
    }

@app.get("/version")
def version_check():
    return {
        "version": "2.3.0",
        "has_cookies": HAS_COOKIES,
        "has_proxy": bool(RESIDENTIAL_PROXY_URL)
    }

@app.get("/search")
def search_tracks(q: str = Query(..., description="Termo de busca")):
    try:
        opts = get_ytdl_search_opts()
        with yt_dlp.YoutubeDL(opts) as ydl:
            results = ydl.extract_info(f"ytsearch15:{q}", download=False)
            tracks = []
            if results and 'entries' in results:
                for entry in results['entries']:
                    if not entry:
                        continue
                    tracks.append({
                        "id": entry.get("id"),
                        "title": entry.get("title", "Sem Título"),
                        "artist": entry.get("uploader", "Artista Desconhecido"),
                        "duration": entry.get("duration", 0),
                        "thumbnail_url": entry.get("thumbnails", [{}])[-1].get("url") if entry.get("thumbnails") else f"https://i.ytimg.com/vi/{entry.get('id')}/hqdefault.jpg"
                    })
            return {"query": q, "results": tracks}
    except Exception as e:
        print("Search error:", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stream/{track_id}")
def get_stream_url(track_id: str):
    try:
        url = f"https://www.youtube.com/watch?v={track_id}"
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
                "stream_url": stream_url
            }
    except Exception as e:
        print("Stream error:", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download/{track_id}")
def proxy_download(track_id: str, request: Request):
    try:
        url = f"https://www.youtube.com/watch?v={track_id}"
        direct_audio_url = None
        ytdl_headers = {}

        try:
            opts = get_ytdl_extract_opts()
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                direct_audio_url = info.get("url")
                ytdl_headers = info.get("http_headers", CHROME_HEADERS)
        except Exception as ex1:
            print("Primary extract failed, trying fallback options:", ex1)
            fallback_opts = get_ytdl_extract_opts()
            fallback_opts['format'] = 'bestaudio/best'

            with yt_dlp.YoutubeDL(fallback_opts) as ydl2:
                info2 = ydl2.extract_info(url, download=False)
                direct_audio_url = info2.get("url")
                ytdl_headers = info2.get("http_headers", CHROME_HEADERS)

        if not direct_audio_url:
            raise HTTPException(status_code=404, detail="Áudio não encontrado.")
        
        # Forward Range header if present
        range_header = request.headers.get("range")
        if range_header:
            ytdl_headers['Range'] = range_header

        proxies_dict = {"http": RESIDENTIAL_PROXY_URL, "https": RESIDENTIAL_PROXY_URL} if RESIDENTIAL_PROXY_URL else None
        resp = requests.get(direct_audio_url, headers=ytdl_headers, stream=True, timeout=25, proxies=proxies_dict)
        
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

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
