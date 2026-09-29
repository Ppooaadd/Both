# syntax=docker/dockerfile:1.7
#
# PianoForge web (Next.js standalone output). Build context: repository root.
#   docker build -f infra/docker/web.Dockerfile .
#
# BACKEND_ORIGIN is baked into the rewrites at build time (fallback proxy for
# /api when the reverse proxy is bypassed). NEXT_PUBLIC_WS_ORIGIN empty means
# "same origin as the page", which is correct behind the reverse proxy.

ARG NODE_IMAGE=node:22-bookworm-slim

FROM ${NODE_IMAGE} AS deps
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca; fi \
 && npm ci --no-audit --no-fund

FROM ${NODE_IMAGE} AS build
ARG BACKEND_ORIGIN=http://api:8000
ARG NEXT_PUBLIC_WS_ORIGIN=
ENV NEXT_TELEMETRY_DISABLED=1 BACKEND_ORIGIN=${BACKEND_ORIGIN} NEXT_PUBLIC_WS_ORIGIN=${NEXT_PUBLIC_WS_ORIGIN}
WORKDIR /web
COPY --from=deps /web/node_modules ./node_modules
COPY apps/web ./
# next/font downloads Google Fonts at build time.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca; fi \
 && npm run build

FROM ${NODE_IMAGE} AS runner
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
COPY --from=build --chown=node:node /web/.next/standalone ./
COPY --from=build --chown=node:node /web/.next/static ./.next/static
COPY --from=build --chown=node:node /web/public ./public
USER node
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=5 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
