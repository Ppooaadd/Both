# syntax=docker/dockerfile:1.7
#
# PianoForge backend image, one Dockerfile with two targets:
#   api     FastAPI (uvicorn)                            ~ small, no audio tools
#   worker  Celery worker/beat: ffmpeg, FluidSynth + SoundFont, cairo (PDF),
#           and (WITH_ML=true, default) Demucs, Basic Pitch and Beat This! with
#           preloaded weights
#
# Build context: repository root.
#   docker build -f infra/docker/backend.Dockerfile --target api .
#   docker build -f infra/docker/backend.Dockerfile --target worker --build-arg WITH_ML=false .
#
# Behind a TLS-intercepting proxy, pass its CA as a build secret (optional):
#   docker build --secret id=extra_ca,src=/path/ca.crt ...

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# ----------------------------------------------------------------------------- base
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # librosa/numba and matplotlib want writable caches; the root FS is read-only at runtime.
    NUMBA_CACHE_DIR=/tmp/numba \
    MPLCONFIGDIR=/tmp/matplotlib \
    HOME=/tmp

RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then \
      cp /run/secrets/extra_ca /usr/local/share/ca-certificates/extra-ca.crt && update-ca-certificates; \
    fi \
 # Fetch packages over HTTPS (the slim image already ships ca-certificates).
 && sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
 && apt-get update \
 && apt-get install -y --no-install-recommends tini \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

# Dependencies first (cached until pyproject.toml changes).
COPY backend/pyproject.toml ./pyproject.toml
RUN --mount=type=secret,id=extra_ca,required=false \
    python -c "import tomllib; print(chr(10).join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" \
      > /tmp/requirements.txt \
 && PIP_CERT=/etc/ssl/certs/ca-certificates.crt pip install -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

# Application source is copied last in each target, so code changes rebuild in
# seconds instead of re-installing dependencies (and ML wheels in the worker).

# ------------------------------------------------------------------------------ api
FROM base AS api
COPY backend/src ./src
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
COPY backend/README.md ./README.md
RUN pip install --no-deps . && python -c "import pianoforge; print(pianoforge.__version__)"

USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"
ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "pianoforge.api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--workers", "2"]

# --------------------------------------------------------------------------- worker
FROM base AS worker
ARG WITH_ML=true
# CPU wheels by default; the GPU overlay passes a CUDA index (e.g. .../whl/cu126).
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
ARG TORCH_VERSION=2.11.0
# Beat This! (ISMIR 2024) checkpoint, MIT licence.
ARG BEAT_THIS_URL=https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/final0.ckpt
# Model caches live in the image (the runtime /tmp is an empty tmpfs). Demucs 4.1
# fetches its weights through the Hugging Face hub.
ENV TORCH_HOME=/opt/models/torch \
    HF_HOME=/opt/models/hf \
    PF_SOUNDFONT_PATH=/usr/share/sounds/sf2/FluidR3_GM.sf2

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fluidsynth fluid-soundfont-gm libcairo2 \
 && rm -rf /var/lib/apt/lists/*

# Basic Pitch's package metadata pins TensorFlow on Linux; the ONNX model needs only
# onnxruntime, so it is installed without dependencies (saves ~1.5 GB and keeps numpy 2).
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ "$WITH_ML" = "true" ]; then \
      export PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
      && pip install "torch==${TORCH_VERSION}" "torchaudio==${TORCH_VERSION}" --index-url "${TORCH_INDEX}" \
      && pip install "demucs==4.1.0" "onnxruntime>=1.18" "mir-eval>=0.7" "pretty-midi>=0.2.10" \
                     "resampy>=0.4" "scikit-learn>=1.3" \
      && pip install --no-deps "basic-pitch==0.4.0" \
      && pip install "beat-this==1.1.0" "einops>=0.7" "rotary-embedding-torch>=0.6" "soxr>=0.3" \
      && mkdir -p /opt/models/torch \
      && REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
         python -c "from demucs.pretrained import get_model; get_model('htdemucs')" \
      && python -c "import basic_pitch; print('basic-pitch model:', basic_pitch.ICASSP_2022_MODEL_PATH)" \
      && mkdir -p /opt/models/beat_this \
      && SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt python -c "import urllib.request as u; u.urlretrieve('${BEAT_THIS_URL}', '/opt/models/beat_this/final0.ckpt')" \
      && python -c "from beat_this.inference import load_model; load_model('/opt/models/beat_this/final0.ckpt'); print('beat_this model ok')" \
      && chmod -R a+rX /opt/models; \
    fi
# Weights were fetched above: never reach the network for them at runtime.
ENV HF_HUB_OFFLINE=1

COPY backend/src ./src
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
COPY backend/README.md ./README.md
RUN pip install --no-deps . && python -c "import pianoforge; print(pianoforge.__version__)"

USER app
ENTRYPOINT ["tini", "--"]
CMD ["celery", "-A", "pianoforge.worker.celery_app", "worker", "-Q", "cpu,ml", "-c", "2", "--prefetch-multiplier", "1"]
