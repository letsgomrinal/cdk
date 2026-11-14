#!/usr/bin/env bash
# Release helper called by Drone. Terraform (via Atlantis) creates the resources;
# this script only rolls out new code.
#
# Workloads are found by the labels the kit puts on everything (product, workload-type),
# so nothing has to list workloads twice.
#
#   release.sh images   <project> <region> <product> <image>
#       Deploy one image to every service, job and worker pool of the product.
#       Set WORKLOADS="api,reconcile" to limit it to some workloads.
#
#   release.sh function <project> <region> <product> <workload> <source_dir> <entry> <base_image>
#       Build and deploy a Cloud Run function from source.
set -euo pipefail

cmd=${1:?usage: release.sh images|function ...}; shift

selected() { [[ -z "${WORKLOADS:-}" || ",${WORKLOADS}," == *",$1,"* ]]; }

case "$cmd" in
  images)
    project=$1 region=$2 product=$3 image=$4
    common=(--project "$project" --region "$region" --quiet)
    filter="metadata.labels.product=${product}"

    for name in $(gcloud run services list --project "$project" --region "$region" \
        --filter="${filter} AND metadata.labels.workload-type=service" --format='value(metadata.name)'); do
      wl=${name#"${product}-"}; wl=${wl%-svc}
      selected "$wl" || continue
      echo "service     $name <- $image"
      gcloud run services update "$name" --image "$image" "${common[@]}"
    done

    for name in $(gcloud run jobs list --project "$project" --region "$region" \
        --filter="${filter} AND metadata.labels.workload-type=job" --format='value(metadata.name)'); do
      wl=${name#"${product}-"}; wl=${wl%-job}
      selected "$wl" || continue
      echo "job         $name <- $image"
      gcloud run jobs update "$name" --image "$image" "${common[@]}"
    done

    for name in $(gcloud beta run worker-pools list --project "$project" --region "$region" \
        --filter="${filter} AND metadata.labels.workload-type=worker-pool" --format='value(metadata.name)'); do
      wl=${name#"${product}-"}; wl=${wl%-wp}
      selected "$wl" || continue
      echo "worker-pool $name <- $image"
      gcloud beta run worker-pools deploy "$name" --image "$image" "${common[@]}"
    done
    ;;

  function)
    project=$1 region=$2 product=$3 workload=$4 source=$5 entry=$6 base_image=$7
    name="${product}-${workload}-fn"
    echo "function    $name <- $source ($entry, $base_image)"
    gcloud run deploy "$name" --source "$source" --function "$entry" --base-image "$base_image" \
      --project "$project" --region "$region" --quiet
    ;;

  *) echo "unknown command: $cmd" >&2; exit 2 ;;
esac
