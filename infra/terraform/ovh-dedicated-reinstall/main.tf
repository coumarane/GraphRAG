locals {
  common_customizations = {
    language = "en-us"
  }

  ssh_private_key_path = pathexpand(var.ssh_private_key_path)
  ssh_keygen_script    = <<-EOT
    set -euo pipefail
    private_key_path="$1"
    key_comment="$2"

    mkdir -p "$(dirname "$private_key_path")"
    if [ ! -f "$private_key_path" ]; then
      ssh-keygen -t ed25519 -N "" -f "$private_key_path" -C "$key_comment" >/dev/null
      chmod 600 "$private_key_path"
      chmod 644 "$private_key_path.pub"
    fi

    python3 -c 'import json, pathlib, sys; private_key_path = pathlib.Path(sys.argv[1]).expanduser(); public_key = pathlib.Path(f"{private_key_path}.pub"); print(json.dumps({"private_key_path": str(private_key_path), "public_key": public_key.read_text(encoding="utf-8").strip()}))' "$private_key_path"
  EOT
  effective_ssh_public_key = coalesce(
    var.ssh_public_key,
    try(data.external.ssh_key_pair[0].result.public_key, null),
  )
}

data "ovh_dedicated_installation_template" "ubuntu" {
  template_name = var.installation_template_name
}

data "azurerm_key_vault" "shared" {
  name                = var.azure_key_vault_name
  resource_group_name = var.azure_resource_group_name
}

data "external" "ssh_key_pair" {
  count = var.auto_generate_ssh_key && var.ssh_public_key == null ? 1 : 0

  program = [
    "/bin/bash",
    "-c",
    local.ssh_keygen_script,
    "bash",
    local.ssh_private_key_path,
    var.ssh_key_comment,
  ]
}

resource "azurerm_key_vault_secret" "ssh_private_key" {
  count = var.manage_ssh_key_in_key_vault && var.auto_generate_ssh_key && var.ssh_public_key == null ? 1 : 0

  name             = var.ssh_private_key_secret_name
  key_vault_id     = data.azurerm_key_vault.shared.id
  value_wo         = file(data.external.ssh_key_pair[0].result.private_key_path)
  value_wo_version = var.ssh_private_key_secret_version
  content_type     = "application/x-pem-file"
}

resource "azurerm_key_vault_secret" "ssh_public_key" {
  count = var.manage_ssh_key_in_key_vault && var.auto_generate_ssh_key && var.ssh_public_key == null ? 1 : 0

  name         = var.ssh_public_key_secret_name
  key_vault_id = data.azurerm_key_vault.shared.id
  value        = data.external.ssh_key_pair[0].result.public_key
  content_type = "text/plain"
}

resource "ovh_dedicated_server_reinstall_task" "cluster" {
  for_each = var.servers

  service_name = each.value.service_name
  os           = data.ovh_dedicated_installation_template.ubuntu.template_name

  lifecycle {
    precondition {
      condition     = local.effective_ssh_public_key != null && local.effective_ssh_public_key != ""
      error_message = "No SSH public key is available. Provide ssh_public_key or enable auto_generate_ssh_key."
    }
  }

  customizations {
    hostname                 = each.value.hostname
    post_installation_script = var.post_installation_script_base64
    ssh_key                  = local.effective_ssh_public_key
    language                 = local.common_customizations.language
  }

  storage {
    partitioning {
      scheme_name = var.scheme_name

      # The OVH cluster README recommends a 120 GB disk split with a dedicated /data mount.
      layout {
        file_system = "ext4"
        mount_point = "/boot"
        size        = 1024
      }

      layout {
        file_system = "ext4"
        mount_point = "/"
        size        = 35840
      }

      layout {
        file_system = "ext4"
        mount_point = "/var"
        size        = 20480
      }

      layout {
        file_system = "swap"
        mount_point = "swap"
        size        = 4096
      }

      layout {
        file_system = "ext4"
        mount_point = "/data"
        size        = 0
      }
    }
  }

  depends_on = [
    azurerm_key_vault_secret.ssh_private_key,
    azurerm_key_vault_secret.ssh_public_key,
  ]
}
