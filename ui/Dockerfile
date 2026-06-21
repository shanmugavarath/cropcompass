# ── Stage 1: build the Vite bundle ───────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

# Install deps in a separate layer so changes to src don't re-download packages.
COPY ui/package.json ui/package-lock.json* ./
RUN npm ci --ignore-scripts

# Inject runtime API addresses as Vite compile-time substitutions.
# These become import.meta.env.VITE_* inside the bundle and must be correct for
# the browsers that will load the page (i.e. host-visible URLs, not Docker-internal ones).
ARG VITE_API_URL=http://localhost:8000
ARG VITE_WS_URL=ws://localhost:8001
ARG VITE_USE_MOCK=false
ENV VITE_API_URL=$VITE_API_URL \
    VITE_WS_URL=$VITE_WS_URL \
    VITE_USE_MOCK=$VITE_USE_MOCK

# Copy the full ui/ tree and build.
COPY ui/ .
RUN npm run build
# Output: /app/dist

# ── Stage 2: serve with Nginx ─────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runner

# SPA routing + caching rules (see ui/nginx.conf)
COPY ui/nginx.conf /etc/nginx/conf.d/default.conf

# Copy the compiled bundle from stage 1
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
