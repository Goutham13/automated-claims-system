FROM oven/bun:1 AS builder

WORKDIR /app

COPY package.json bun.lockb ./
RUN bun install --frozen-lockfile

COPY . .

ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN bun run build

# Show build output so we can verify structure in CI logs
RUN echo "=== Build output ===" && \
    find /app -maxdepth 5 -not -path "*/node_modules/*" \( -type d -o -name "*.mjs" -o -name "*.js" \) | sort | head -80

# ---- runner ----
FROM node:20-slim AS runner

WORKDIR /app

# Copy the entire app (includes .output or dist from build)
COPY --from=builder /app/.output ./.output
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json

ENV PORT=8080
ENV NODE_ENV=production

EXPOSE 8080

# Start the server — TanStack Start node-server preset outputs to .output/server/index.mjs
CMD ["sh", "-c", "\
  if [ -f .output/server/index.mjs ]; then \
    echo 'Starting from .output/server/index.mjs'; \
    exec node .output/server/index.mjs; \
  elif [ -f dist/server/index.js ]; then \
    echo 'Starting from dist/server/index.js'; \
    exec node dist/server/index.js; \
  else \
    echo 'ERROR: No server entry found. Contents:'; \
    find /app -maxdepth 5 -not -path '*/node_modules/*' | sort; \
    exit 1; \
  fi"]
