FROM node:22-alpine AS web

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY index.html tsconfig.json tsconfig.node.json vite.config.ts ./
COPY public ./public
COPY src ./src
RUN npm run build

FROM python:3.13-slim

WORKDIR /app
ENV AUTOCORE_HOST=0.0.0.0
ENV AUTOCORE_PORT=8787
ENV AUTOCORE_MODE=public
ENV AUTOCORE_STATIC_DIR=/app/dist
ENV PYTHONUNBUFFERED=1

COPY --from=web /app/dist /app/dist
COPY autocore /app/autocore
COPY README.md PORTFOLIO_CASE_STUDY.md ./

EXPOSE 8787
CMD ["python", "-m", "autocore.server"]
