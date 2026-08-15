# Azure Terraform State Bootstrap

Bootstrap stack to create the Azure Blob container used by the main Terraform stack in [../README.md](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/azure/README.md).

Existing shared resources:

- resource group: `rg-safranysAI-Dev`
- storage account: `terraformstate240775`

This bootstrap stack creates:

- blob container: `tfstate-azure`

## Files

- [providers.tf](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/azure/bootstrap-state/providers.tf)
- [variables.tf](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/azure/bootstrap-state/variables.tf)
- [main.tf](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/azure/bootstrap-state/main.tf)
- [outputs.tf](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/azure/bootstrap-state/outputs.tf)
- [terraform.tfvars.example](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/azure/bootstrap-state/terraform.tfvars.example)

## Run

```bash
cd infra/terraform/azure/bootstrap-state
terraform init
terraform apply -var-file=terraform.dev.tfvars
```

After apply, use the output values or [../backend.hcl.example](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/azure/backend.hcl.example) to initialize the main Azure stack.
