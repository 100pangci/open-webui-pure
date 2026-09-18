# Open WebUI

Open WebUI is a self-hosted, lightweight chat interface for OpenAI-compatible
APIs. It provides authenticated conversations, streaming responses, model
selection, local image attachments, and image generation and editing through
the configured OpenAI-compatible provider.

## Features

- OpenAI-compatible chat and image APIs
- User authentication, sessions, roles, and user management
- Streaming chat responses over Socket.IO
- Multiple configured models and per-model system prompts and parameters
- Image generation and image editing
- Local image uploads stored in the application data directory
- SQLite by default, with PostgreSQL support
- Responsive desktop and mobile interface
- Multilingual interface

## Installation

Use Python 3.11 or 3.12 for a native installation:

```bash
pip install open-webui
open-webui serve
```

The server listens on `http://localhost:8080` by default.

## Podman

Build and start the application with the included CPU-only compose file:

```bash
podman compose -f podman-compose.yaml up -d --build
```

The application is available at `http://localhost:3000`. The compose file
preserves the existing `open-webui` volume at `/app/backend/data`; do not use
volume-removal flags when stopping the service if database and uploaded images
must be retained.

Set the provider before starting the service, for example:

```bash
export OPENAI_API_BASE_URL=https://api.openai.com/v1
export OPENAI_API_KEY=your_secret_key
podman compose -f podman-compose.yaml up -d --build
```

Useful commands:

```bash
make startAndBuild
make logs
make health
make stop
```

## Development

Install frontend dependencies and run the development server:

```bash
npm ci
npm run dev
```

Run frontend checks and tests:

```bash
npm run check
npm run test:frontend
npm run build
```

## License

This project contains code under multiple licenses. The current codebase
includes components licensed under the Open WebUI License with an additional
requirement to preserve the "Open WebUI" branding, as well as prior
contributions under their respective original licenses. For a detailed record
of license changes and the applicable terms for each section of the code, see
[`LICENSE_HISTORY`](./LICENSE_HISTORY). For complete licensing details, see
[`LICENSE`](./LICENSE) and [`LICENSE_HISTORY`](./LICENSE_HISTORY).

## Support

Open an issue or join the [Open WebUI Discord community](https://discord.gg/5rJgQTnV4s)
for questions and support.

## Security

Report security vulnerabilities through the [responsible disclosure program on
GitHub](https://github.com/open-webui/open-webui/security). Do not disclose
security issues publicly before they have been reviewed.
