variable "env" { type = string }
variable "project_id" { type = string }
variable "region" { type = string }

variable "deployers" {
  type    = list(string)
  default = []
}

variable "vpc" {
  type = object({
    network    = string
    subnetwork = string
    egress     = optional(string, "PRIVATE_RANGES_ONLY")
  })
  default = null
}

variable "deletion_protection" {
  type    = bool
  default = true
}
