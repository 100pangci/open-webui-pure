COMPOSE := podman compose -f podman-compose.yaml

.PHONY: install build start startAndBuild stop remove logs health

install:
	$(COMPOSE) up -d

build:
	$(COMPOSE) build

start:
	$(COMPOSE) start

startAndBuild:
	$(COMPOSE) up -d --build

stop:
	$(COMPOSE) stop

remove:
	$(COMPOSE) down --remove-orphans

logs:
	$(COMPOSE) logs -f open-webui

health:
	curl --fail http://localhost:$${OPEN_WEBUI_PORT:-3000}/health
