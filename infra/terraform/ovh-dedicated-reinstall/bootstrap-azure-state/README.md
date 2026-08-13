# Azure Remote State Bootstrap

This Terraform stack creates the Azure Blob container used by the OVH dedicated server reinstall state backend.

It assumes these Azure resources already exist:

- resource group: `rg-safranysAI-Dev`
- storage account: `terraformstate240775`

It creates:

- blob container: `tfstate-ovh-dedicated-reinstall`

## Run

```bash
az login
az account set --subscription a555786b-b00c-4cea-946c-5c435d5e7100

cd infra/terraform/ovh-dedicated-reinstall/bootstrap-azure-state
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform apply
```

After apply, use the generated values or [../backend.hcl.example](/Users/coumaranecouppane/Dev/ProjetRag/GraphRAG/infra/terraform/ovh-dedicated-reinstall/backend.hcl.example) to initialize the main OVH reinstall stack.
