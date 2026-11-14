output "workloads" {
  description = "Every workload in the product: name, type, runtime SA and (for HTTP workloads) URI."
  value = {
    for key, w in local.workloads : key => {
      type            = w.type
      name            = module.naming[key].name
      service_account = module.identity[key].email
      uri = (
        w.type == "service" ? module.service[w.name].uri :
        w.type == "function" ? module.function[w.name].uri :
        null
      )
    }
  }
}
