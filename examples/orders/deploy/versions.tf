terraform {
  required_version = ">= 1.6"

  required_providers {
    google = { source = "hashicorp/google", version = "~> 8.11" }
  }

  # The bucket comes from env/<env>.backend.hcl (one state bucket per environment).
  # The prefix is the product name, not the repo path, so moving this folder
  # between repos doesn't orphan its state.
  backend "gcs" {
    prefix = "products/orders"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
