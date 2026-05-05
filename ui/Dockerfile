FROM oven/bun:1 AS builder

WORKDIR /app

COPY package.json bun.lockb ./
RUN bun install --frozen-lockfile

COPY . .

ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN bun run build

# Print everything produced by the build so we can find the server entry
RUN echo "===BUILD OUTPUT===" && find /app -not -path "*/node_modules/*" -name "*.mjs" -o -name "*.js" 2>/dev/null | grep -i "server\|index" | head -30

# ---- runner ----
FROM node:20-slim AS runner

WORKDIR /app

COPY --from=builder /app /app

ENV PORT=8080
ENV NODE_ENV=production

EXPOSE 8080

CMD ["sh", "-c", "echo 'files:' && find /app -not -path '*/node_modules/*' -name '*.mjs' | head -20 && exit 1"]
