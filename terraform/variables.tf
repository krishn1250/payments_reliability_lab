variable "cluster_name" {
  type    = string
  default = "payments-lab"
}

variable "kubernetes_version" {
  description = "kindest/node image tag."
  type        = string
  default     = "v1.32.2"
}

variable "worker_count" {
  description = "Workers. 3 lets Postgres instances spread across nodes."
  type        = number
  default     = 3

  validation {
    condition     = var.worker_count >= 1 && var.worker_count <= 5
    error_message = "worker_count must be between 1 and 5."
  }
}

variable "repo_url" {
  description = "Public Git URL Argo CD syncs from (your fork)."
  type        = string
}

variable "target_revision" {
  type    = string
  default = "main"
}

variable "argocd_chart_version" {
  description = "argo-cd Helm chart version. Pin after first successful install."
  type        = string
  default     = "8.*"
}
