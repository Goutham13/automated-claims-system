FROM oven/bun:1 AS builder

WORKDIR /app

COPY package.json bun.lockb ./
RUN bun install --frozen-lockfile

COPY . .

ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN bun run build

# Show full build output structure
RUN echo "===DIRS===" && find /app -maxdepth 4 -not -path "*/node_modules/*" -type d && \
    echo "===FILES===" && find /app -maxdepth 5 -not -path "*/node_modules/*" -type f | head -60

# ---- runner ----
FROM node:20-slim AS runner

WORKDIR /app

COPY --from=builder /app /app

ENV PORT=8080
ENV NODE_ENV=production

EXPOSE 8080

CMD ["sh", "-c", "echo '===DIRS===' && find /app -maxdepth 4 -not -path '*/node_modules/*' -type d && exit 1"]
