# Requirements: docker, kind, kubectl, helm, git. Optional: kubectl-argo-rollouts plugin.
CLUSTER ?= payments-lab
GH_USER ?= $(shell git config --get remote.origin.url | sed -E 's#.*[:/]([^/]+)/[^/]+(\.git)?$$#\1#')
IMAGE   ?= payments-api:0.1.0
REPO_URL ?= https://github.com/$(GH_USER)/payments-reliability-lab.git
TF      := terraform -chdir=terraform

.PHONY: help init up up-manual tf-apply cluster argocd image secrets down down-manual status argocd-ui grafana rollouts-ui watch \
        release-good release-bad release-slow promote abort test test-idempotency invariants \
        chaos-db-primary chaos-db-latency chaos-db-partition chaos-app-pods chaos-cpu

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

init: ## Point Argo CD apps at your fork (run once)
	./scripts/init.sh $(GH_USER)

up: tf-apply image ## Everything: Terraform (kind, secret, Argo CD, root app) + app image
	@echo "Argo CD is syncing. Watch with: make status"

tf-apply: ## Terraform: kind cluster, webhook secret, Argo CD, root app
	$(TF) init -upgrade
	$(TF) apply -auto-approve -var "repo_url=$(REPO_URL)" -var "cluster_name=$(CLUSTER)"

up-manual: cluster image secrets argocd ## Same as up, with kind/helm/kubectl instead of Terraform
	@echo "Argo CD is syncing. Watch with: make status"

cluster: ## Create the kind cluster
	kind get clusters | grep -qx $(CLUSTER) || kind create cluster --config bootstrap/kind-config.yaml

image: ## Build payments-api and load it into kind
	docker build -t $(IMAGE) services/payments-api
	kind load docker-image $(IMAGE) --name $(CLUSTER)

secrets: ## Create the webhook signing secret (not in Git)
	./scripts/secrets.sh

argocd: ## Install Argo CD and apply the root app
	helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
	helm repo update argo >/dev/null
	helm upgrade --install argocd argo/argo-cd -n argocd --create-namespace -f bootstrap/argocd-values.yaml --wait
	kubectl apply -f argocd/root-app.yaml

down: ## Destroy everything Terraform created
	$(TF) destroy -auto-approve -var "repo_url=$(REPO_URL)" -var "cluster_name=$(CLUSTER)"

down-manual: ## Delete the cluster (manual path)
	kind delete cluster --name $(CLUSTER)

status: ## Apps, rollout, database, pods
	kubectl -n argocd get applications
	kubectl -n payments get rollout,cluster.postgresql.cnpg.io,pods

argocd-ui: ## Argo CD on http://localhost:8081 (user admin, password printed)
	@echo "password: $$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)"
	kubectl -n argocd port-forward svc/argocd-server 8081:80

grafana: ## Grafana on http://localhost:3000 (admin / admin)
	kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80

rollouts-ui: ## Argo Rollouts dashboard on http://localhost:3100
	kubectl -n argo-rollouts port-forward svc/argo-rollouts-dashboard 3100:3100

watch: ## Live view of the canary (needs kubectl-argo-rollouts plugin)
	kubectl argo rollouts get rollout payments-api -n payments --watch

release-good: ## Healthy release -> should reach 100%
	./scripts/release.sh v2

release-bad: ## 20% errors -> analysis should abort and roll back
	./scripts/release.sh v3-bad --fault 0.2

release-slow: ## +400ms latency -> analysis should abort on p95
	./scripts/release.sh v4-slow --latency 400

promote: ## Skip remaining pauses
	kubectl argo rollouts promote payments-api -n payments

abort: ## Manually abort the current canary
	kubectl argo rollouts abort payments-api -n payments

test: ## Unit tests (domain logic, no DB needed)
	cd services/payments-api && python -m pytest -q tests/test_domain.py

test-idempotency: ## 50 concurrent identical requests -> exactly 1 payment
	./scripts/test-idempotency.sh 50

invariants: ## Check business invariants in Postgres
	./scripts/check-invariants.sh

chaos-db-primary: ## Kill the Postgres primary
	./scripts/chaos.sh db-primary-kill 120

chaos-db-latency: ## +150ms between app and DB for 5m
	./scripts/chaos.sh db-network-latency 300

chaos-db-partition: ## Cut app off from DB for 45s
	./scripts/chaos.sh db-partition 90

chaos-app-pods: ## Kill an app pod every 30s for 3m
	./scripts/chaos.sh app-pod-kill 180

chaos-cpu: ## CPU stress on app pods for 3m
	./scripts/chaos.sh app-cpu-stress 180
