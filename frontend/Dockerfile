FROM node:22-alpine AS builder

WORKDIR /app

COPY package*.json ./

RUN npm ci

COPY . .

ARG VITE_API_BASE_URL
ARG VITE_GOOGLE_CLIENT_ID

ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID

RUN npm run build


FROM caddy:2-alpine

COPY --from=builder /app/dist /srv

COPY Caddyfile /etc/caddy/Caddyfile

EXPOSE 80
