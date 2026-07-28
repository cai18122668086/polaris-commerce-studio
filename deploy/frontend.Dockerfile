# syntax=docker/dockerfile:1.7

FROM node:22.22.0-bookworm-slim AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

FROM dependencies AS build
COPY .openai/hosting.json .openai/hosting.json
COPY app app
COPY build build
COPY components components
COPY db db
COPY drizzle drizzle
COPY features features
COPY lib lib
COPY public public
COPY worker worker
COPY drizzle.config.ts eslint.config.mjs next.config.ts ./
COPY postcss.config.mjs tsconfig.json vite.config.ts ./
RUN npm run build

FROM node:22.22.0-bookworm-slim AS runtime
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
COPY --from=build --chown=node:node /app /app
USER node
EXPOSE 3000
CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
