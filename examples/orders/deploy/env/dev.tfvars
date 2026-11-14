env        = "dev"
project_id = "acme-orders-dev"
region     = "europe-west1"

deployers = ["serviceAccount:drone-release@acme-cicd.iam.gserviceaccount.com"]

vpc = {
  network    = "projects/acme-net-dev/global/networks/shared"
  subnetwork = "projects/acme-net-dev/regions/europe-west1/subnetworks/serverless"
}

deletion_protection = false
