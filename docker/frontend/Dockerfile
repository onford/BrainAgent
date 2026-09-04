FROM node:22-alpine

WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY frontend .

EXPOSE 5173
CMD ["pnpm", "run", "dev:web"]
