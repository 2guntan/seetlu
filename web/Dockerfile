# dev: Vite dev server (docker-compose.yml). prod: static build served by Caddy (ops/docker-compose.prod.yml).
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM deps AS build
COPY . .
RUN npm run build

FROM caddy:2.8.4-alpine AS prod
COPY --from=build /app/dist /srv/web

FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]
