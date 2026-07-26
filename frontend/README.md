# Vachan frontend

SvelteKit operator console for the Vachan demo. The repository-level [README](../README.md)
describes the product, trust model, and local two-process setup; [AGENTS.md](../AGENTS.md) is the
authoritative operating manual.

Use bun for every frontend dependency and script:

```sh
bun install
bun run dev
bun test
bun run check
bun run build
```

The development server runs on port 3000 and proxies `/api` and `/ws` to the FastAPI backend on
port 8000. Run the stage demo from `http://localhost:3000` with wired headphones.
