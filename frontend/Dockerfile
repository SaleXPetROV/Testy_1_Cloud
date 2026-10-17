# GRAM City frontend: build with Node, serve with nginx (+ /api proxy to the backend)
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install --legacy-peer-deps --no-audit --no-fund && npm install --no-save --legacy-peer-deps ajv@8
COPY . .
# public address of the site; nginx in this image proxies /api and WebSockets
ARG REACT_APP_BACKEND_URL="http://localhost:8080"
ARG REACT_APP_ADMIN_PATH=""
# INLINE_RUNTIME_CHUNK=false: the webpack runtime goes to a file, so the CSP hashes stay valid
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL REACT_APP_ADMIN_PATH=$REACT_APP_ADMIN_PATH CI=false INLINE_RUNTIME_CHUNK=false
RUN npx craco build && node scripts/csp.js

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build /usr/share/nginx/html
COPY --from=build /app/build/csp.conf /etc/nginx/snippets/csp.conf
EXPOSE 80
