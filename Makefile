.PHONY: install-docker up down db-shell apply-schema verify-db logs

# Step 1 — Install Docker Engine on WSL2 (run once)
install-docker:
	bash infra/install_docker.sh

# Step 2 — Copy .env and start containers
setup-env:
	@test -f .env || (cp .env.example .env && echo ".env created — fill in ANTHROPIC_API_KEY")

# Step 3 — Start all services (db + vectordb + api)
up: setup-env
	docker compose up -d

# Bring everything down (data volumes preserved)
down:
	docker compose down

# Destroy all including volumes (CAUTION: drops all data)
destroy:
	docker compose down -v

# Connect to PostgreSQL shell
db-shell:
	docker exec -it cropcompass-db psql -U cropcompass -d cropcompass

# Apply schema manually (auto-applied on first start via initdb)
apply-schema:
	docker exec -i cropcompass-db psql -U cropcompass -d cropcompass < db/schema.sql

# Verify pgvector extension and tables exist
verify-db:
	docker exec -it cropcompass-db psql -U cropcompass -d cropcompass -c \
		"SELECT extname, extversion FROM pg_extension; \dt"

# Test mark_stale_records() function
test-stale-fn:
	docker exec -it cropcompass-db psql -U cropcompass -d cropcompass -c \
		"SELECT mark_stale_records();"

# Tail all container logs
logs:
	docker compose logs -f

# Tail DB logs only
logs-db:
	docker compose logs -f db

# Show district count in imd_advisories
check-imd:
	docker exec -it cropcompass-db psql -U cropcompass -d cropcompass -c \
		"SELECT state, COUNT(DISTINCT district) AS districts, COUNT(*) AS records FROM imd_advisories GROUP BY state ORDER BY state;"

# Show reference districts loaded
check-districts:
	docker exec -it cropcompass-db psql -U cropcompass -d cropcompass -c \
		"SELECT state, COUNT(*) FROM imd_districts_ref GROUP BY state ORDER BY state;"
