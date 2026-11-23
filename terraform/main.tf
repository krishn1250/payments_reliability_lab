# Terraform owns only what has to exist before GitOps can start:
#   cluster -> secrets that must not live in Git -> Argo CD -> root app.
# Everything else (operators, monitoring, the app) is reconciled by Argo CD.

resource "kind_cluster" "this" {
  name           = var.cluster_name
  node_image     = "kindest/node:${var.kubernetes_version}"
  wait_for_ready = true

  kind_config {
    kind        = "Cluster"
    api_version = "kind.x-k8s.io/v1alpha4"

    node {
      role = "control-plane"
    }

    dynamic "node" {
      for_each = range(var.worker_count)
      content {
        role = "worker"
      }
    }
  }
}

provider "kubernetes" {
  host                   = kind_cluster.this.endpoint
  client_certificate     = kind_cluster.this.client_certificate
  client_key             = kind_cluster.this.client_key
  cluster_ca_certificate = kind_cluster.this.cluster_ca_certificate
}

provider "helm" {
  kubernetes = {
    host                   = kind_cluster.this.endpoint
    client_certificate     = kind_cluster.this.client_certificate
    client_key             = kind_cluster.this.client_key
    cluster_ca_certificate = kind_cluster.this.cluster_ca_certificate
  }
}

# ---- secrets that must not be in Git ----

resource "kubernetes_namespace_v1" "payments" {
  metadata {
    name = "payments"
  }
  # Argo CD also manages this namespace (CreateNamespace=true); let it add labels.
  lifecycle {
    ignore_changes = [metadata[0].labels, metadata[0].annotations]
  }
}

# Note: the value ends up in Terraform state. Fine for a laptop; in a real
# setup the secret lives in Vault/Key Vault and External Secrets syncs it.
resource "random_password" "webhook" {
  length  = 48
  special = false
}

resource "kubernetes_secret_v1" "webhook" {
  metadata {
    name      = "payments-webhook"
    namespace = kubernetes_namespace_v1.payments.metadata[0].name
  }
  data = {
    secret = "whsec_${random_password.webhook.result}"
  }
}

# ---- GitOps bootstrap ----

resource "helm_release" "argocd" {
  name             = "argocd"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  version          = var.argocd_chart_version
  namespace        = "argocd"
  create_namespace = true
  wait             = true
  timeout          = 600

  values = [file("${path.module}/../bootstrap/argocd-values.yaml")]
}

# The root Application is created through the argocd-apps chart instead of a
# kubernetes_manifest, because kubernetes_manifest needs the Application CRD
# to exist at plan time, which fails on a fresh cluster.
resource "helm_release" "root_app" {
  name       = "root-app"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argocd-apps"
  namespace  = "argocd"

  values = [templatefile("${path.module}/root-app.yaml.tftpl", {
    repo_url        = var.repo_url
    target_revision = var.target_revision
  })]

  depends_on = [helm_release.argocd, kubernetes_secret_v1.webhook]
}
