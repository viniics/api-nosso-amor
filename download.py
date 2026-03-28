import os
import json
import subprocess
import tempfile
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
from dotenv import load_dotenv

# Pega a pasta atual (api), sobe um nível (nosso-amor) e acha o .env.local
caminho_env = Path(__file__).parent.parent / ".env.local"
load_dotenv(caminho_env)

app = FastAPI()

# CORS — permite chamadas do Next.js
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

supabase_url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
supabase_key = os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY") 

supabase = create_client(supabase_url, supabase_key)


BUCKET = "assets"
PASTA_TEMP   = "musicas-temp"    # aguardando pagamento
PASTA_PERM   = "musicas"         # pagamento confirmado


# ── STREAMING — preview sem salvar nada ──────────────────────────────────────
@app.get("/stream")
async def stream_audio(video_id: str):
    """
    Faz pipe do yt-dlp direto pro browser.
    O browser começa a tocar nos primeiros segundos.
    Nada é salvo em disco ou no banco.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"

    process = subprocess.Popen(
        [
            "yt-dlp",
            "-f", "m4a/bestaudio/best",
            "--no-playlist",
            "--quiet",
            "-o", "-",          # stdout
            url,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    def generator():
        try:
            while True:
                chunk = process.stdout.read(32768)  # 32kb por chunk
                if not chunk:
                    break
                yield chunk
        finally:
            process.kill()

    return StreamingResponse(
        generator(),
        media_type="audio/mp4",
        headers={
            "Cache-Control": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ── DOWNLOAD + UPLOAD TEMP — chamado antes do pagamento ──────────────────────
class DownloadPayload(BaseModel):
    videoId: str
    titulo: str


@app.post("/download")
async def download_audio(payload: DownloadPayload):
    """
    1. Verifica se já existe no bucket permanente → retorna URL direto (custo zero)
    2. Verifica se já existe no bucket temp → retorna URL direto
    3. Baixa, salva em temp, retorna URL
    """
    video_id = payload.videoId
    arquivo_perm = f"{PASTA_PERM}/{video_id}.m4a"
    arquivo_temp = f"{PASTA_TEMP}/{video_id}.m4a"

    # — Verifica bucket permanente primeiro —
    try:
        existing = supabase.storage.from_(BUCKET).list(PASTA_PERM, {"search": f"{video_id}.m4a"})
        if existing and len(existing) > 0:
            url = supabase.storage.from_(BUCKET).get_public_url(arquivo_perm)
            return {"audioUrl": url, "cached": True, "bucket": "permanente"}
    except Exception:
        pass

    # — Verifica bucket temp —
    try:
        existing_temp = supabase.storage.from_(BUCKET).list(PASTA_TEMP, {"search": f"{video_id}.m4a"})
        if existing_temp and len(existing_temp) > 0:
            url = supabase.storage.from_(BUCKET).get_public_url(arquivo_temp)
            return {"audioUrl": url, "cached": True, "bucket": "temp"}
    except Exception:
        pass

    # — Baixa o arquivo —
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = str(Path(tmpdir) / f"{video_id}.m4a")

        result = subprocess.run(
            [
                "yt-dlp",
                "-f", "m4a/bestaudio/best",
                "--no-playlist",
                "--max-filesize", "30M",
                "--quiet",
                "-o", output_path,
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            capture_output=True,
            timeout=120,
        )

        if result.returncode != 0:
            erro_real = result.stderr.decode('utf-8', errors='ignore')
            print(f"🚨 ERRO DO YT-DLP: {erro_real}")
            raise HTTPException(status_code=500, detail="Falha ao baixar o áudio do YouTube.")

        with open(output_path, "rb") as f:
            file_bytes = f.read()

    # — Salva no bucket temp —
    supabase.storage.from_(BUCKET).upload(
        path=arquivo_temp,
        file=file_bytes,
        file_options={"content-type": "audio/mp4", "upsert": "true"},
    )

    url = supabase.storage.from_(BUCKET).get_public_url(arquivo_temp)
    return {"audioUrl": url, "cached": False, "bucket": "temp"}


# ── PROMOVER — chamado após pagamento confirmado ──────────────────────────────
class PromoverPayload(BaseModel):
    videoId: str


@app.post("/promover")
async def promover_audio(payload: PromoverPayload):
    """
    Move o arquivo de musicas-temp/ para musicas/.
    Chamado pelo webhook de pagamento após confirmação.
    """
    video_id = payload.videoId
    origem  = f"{PASTA_TEMP}/{video_id}.m4a"
    destino = f"{PASTA_PERM}/{video_id}.m4a"

    # Verifica se já está no permanente
    try:
        existing = supabase.storage.from_(BUCKET).list(PASTA_PERM, {"search": f"{video_id}.m4a"})
        if existing and len(existing) > 0:
            url = supabase.storage.from_(BUCKET).get_public_url(destino)
            return {"audioUrl": url, "status": "ja_permanente"}
    except Exception:
        pass

    # Copia temp → permanente
    supabase.storage.from_(BUCKET).copy(origem, destino)
    supabase.storage.from_(BUCKET).remove([origem])

    url = supabase.storage.from_(BUCKET).get_public_url(destino)
    return {"audioUrl": url, "status": "promovido"}


# — Health check —
@app.get("/health")
async def health():
    return {"status": "ok"}