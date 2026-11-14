env        = "prod"
project_id = "acme-orders-prod"
region     = "europe-west1"

deployers = ["serviceAccount:drone-release@acme-cicd.iam.gserviceaccount.com"]

vpc = {
  network    = "projects/acme-net-prod/global/networks/shared"
  subnetwork = "projects/acme-net-prod/regions/europe-west1/subnetworks/serverless"
}
