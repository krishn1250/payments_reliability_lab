output "kube_context" {
  value = "kind-${var.cluster_name}"
}

output "argocd_password_command" {
  description = "Run this to get the Argo CD admin password."
  value       = "kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
}
