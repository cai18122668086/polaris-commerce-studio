ARG POLARIS_VIDEO_FRONTEND_BASE_IMAGE
FROM ${POLARIS_VIDEO_FRONTEND_BASE_IMAGE}
USER root
WORKDIR /app
RUN node -e 'const fs = require("node:fs"); const p = JSON.parse(fs.readFileSync("package.json", "utf8")); p.dependencies.react = "19.2.9"; p.dependencies["react-dom"] = "19.2.9"; p.devDependencies["react-server-dom-webpack"] = "19.2.9"; fs.writeFileSync("package.json", JSON.stringify(p, null, 2) + "\n");' \
    && npm install --include=dev --ignore-scripts \
    && npm audit --include=dev --audit-level=high
# Retain the currently deployed commerce UI and patch only the reviewed video UI.
COPY app/video-studio ./app/video-studio
COPY components/video-studio ./components/video-studio
COPY features/video-studio ./features/video-studio
COPY lib/api/generated/openapi.d.ts ./lib/api/generated/openapi.d.ts
RUN npm run typecheck && npm run build
ARG POLARIS_RELEASE_REVISION
LABEL org.opencontainers.image.revision=${POLARIS_RELEASE_REVISION}
USER 1000:1000
