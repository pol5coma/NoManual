# The web app: built with Vite, served by nginx.
#
# Node is only needed to produce the bundle, so it stays in the first stage.
# What ships is static files behind a web server, which is all a single-page
# app ever needs.

FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite inlines env vars at build time, so the API URL is baked into the bundle
# here rather than read at runtime. That is also why it must never hold a
# secret: anything VITE_ prefixed ends up in the browser.
ARG VITE_API_URL=http://127.0.0.1:8000
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build


FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
