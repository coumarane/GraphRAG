# Azure Configuration
azure_subscription_id     = "a555786b-b00c-4cea-946c-5c435d5e7100"
azure_tenant_id           = "f387bed5-f1ed-4801-9df7-837a8905a354"
azure_resource_group_name = "rg-safranysAI-Dev"
azure_key_vault_name      = "safranys-kv-shared"

# OVH Dedicated Server Reinstallation Configuration
installation_template_name      = "ubuntu2604-server"
auto_generate_ssh_key           = true
ssh_private_key_path            = "~/.ssh/ovh-rag-reinstall-ed25519"
manage_ssh_key_in_key_vault     = true
ssh_private_key_secret_name     = "ovh-rag-reinstall-ssh-private-key"
ssh_private_key_secret_version  = 1
ssh_public_key_secret_name      = "ovh-rag-reinstall-ssh-public-key"
ssh_public_key                  = null
post_installation_script_base64 = null
scheme_name                     = null

servers = {
  master = {
    service_name = "ns3063017.ip-193-70-35.eu"
    hostname     = "rag-master"
    role         = "master"
    ip           = "193.70.35.121"
  }
  worker1 = {
    service_name = "ns3063022.ip-193-70-35.eu"
    hostname     = "rag-worker-1"
    role         = "worker"
    ip           = "193.70.35.122"
  }
  worker2 = {
    service_name = "ns3086111.ip-145-239-68.eu"
    hostname     = "rag-worker-2"
    role         = "worker"
    ip           = "145.239.68.200"
  }
}
