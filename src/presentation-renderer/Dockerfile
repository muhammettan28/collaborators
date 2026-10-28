# The presentation renderer: PDFs of HTML presentations (README.md).
# trixie: its chromium is current, and built for x86 and ARM alike.
FROM node:22-trixie-slim AS base

# Upgrade system packages to install security updates. Chromium draws the
# slides; DejaVu writes the dated page (Turkish, French… letters); Noto and
# Liberation stand in for the fonts presentations ask for by name.
RUN apt-get update && \
  apt-get upgrade -y && \
  apt-get install -y --no-install-recommends \
    chromium fonts-dejavu-core fonts-liberation fonts-noto-core \
    fonts-noto-color-emoji ca-certificates && \
  rm -rf /var/lib/apt/lists/*

WORKDIR /app

# built from the repository root, like every other image here
COPY ./src/presentation-renderer/package.json ./src/presentation-renderer/yarn.lock ./


# ---- Build stage ----
FROM base AS presentation-renderer-builder

RUN yarn install --frozen-lockfile

COPY ./src/presentation-renderer/tsconfig.json ./src/presentation-renderer/tsconfig.build.json ./
COPY ./src/presentation-renderer/src ./src

RUN yarn build


# ---- Production image ----
FROM base AS presentation-renderer

RUN yarn install --frozen-lockfile --production && \
  yarn cache clean

# npm is not needed at runtime and bundles its own, rarely updated, dependencies
RUN rm -rf /usr/local/bin/npm /usr/local/bin/npx /usr/local/lib/node_modules/npm

COPY --from=presentation-renderer-builder /app/dist ./dist

ENV CHROMIUM_PATH=/usr/bin/chromium
EXPOSE 3010

COPY ./docker/files/usr/local/bin/entrypoint /usr/local/bin/entrypoint
RUN chmod g=u /etc/passwd

# Un-privileged user; Chromium needs a home to write its profile in
ARG DOCKER_USER=1000
ENV HOME=/tmp
USER ${DOCKER_USER}

ENTRYPOINT [ "/usr/local/bin/entrypoint" ]

CMD ["node", "dist/server.js"]
