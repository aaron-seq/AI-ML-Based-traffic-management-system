# Frontend image: builds the dashboard and serves the static bundle with nginx.
#
# Build:  docker build -t traffic-frontend ./frontend
# Run:    alongside the backend, e.g. `docker compose up`. nginx resolves its
#         upstream "backend" at start-up and exits if no such host exists.
#
# The bundle is static, so VITE_* values are baked in at build time. Pass them
# as build args when the API lives on a different origin to the dashboard.

# ----------------------------------------------------------------- builder ---
FROM node:22-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

ARG VITE_API_URL=""
ARG VITE_WS_URL=""
ENV VITE_API_URL=$VITE_API_URL \
    VITE_WS_URL=$VITE_WS_URL

RUN npm run build

# ----------------------------------------------------------------- runtime ---
FROM nginx:1.29-alpine AS runtime

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf

# The stock nginx.conf writes its pid to root-owned /run and creates temp
# directories under root-owned /var/cache/nginx, so as the nginx user below it
# exits at start-up: mkdir() "/var/cache/nginx/client_temp" failed (13).
# Move the pid to /tmp, give nginx its cache directory (upload bodies buffer
# there), and drop `user`, which only applies when the master runs as root.
RUN sed -i -e 's|^pid .*|pid /tmp/nginx.pid;|' -e '/^user /d' /etc/nginx/nginx.conf \
    && chown -R nginx:nginx /var/cache/nginx

# Port 8080 so the container can run as an unprivileged user; binding below
# 1024 would require extra capabilities.
EXPOSE 8080
USER nginx

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost:8080/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
