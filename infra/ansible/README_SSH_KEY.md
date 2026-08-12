# SSH Public Key

Public SSH key (passphrase example: Password123)
```bash
ssh-keygen -t rsa -b 4096 -C "k8s-master" -f ~/.ssh/id_rsa_k8smaster
ssh-keygen -t rsa -b 4096 -C "k8s-worker" -f ~/.ssh/id_rsa_k8sworker
```

Add Entries to ~/.ssh/config
Use the SSH config file to map keys to hosts:
```bash
# Master node
Host k8s-master
  HostName 193.70.35.121
  User ubuntu
  IdentityFile ~/.ssh/id_rsa_k8smaster
  IdentitiesOnly yes

# Worker node
Host k8s-worker
  HostName 193.70.35.122
  User ubuntu
  IdentityFile ~/.ssh/id_rsa_k8sworker
  IdentitiesOnly yes
```

## Use ssh-agent
1. Start ssh-agent (if not already running):
```bash
eval "$(ssh-agent -s)"
```

2. Add your SSH private key to the agent:
```bash
ssh-add ~/.ssh/id_rsa_k8smaster
ssh-add ~/.ssh/id_rsa_k8sworker
```

3. Verify your key is added:
```bash
ssh-add -l
```

## Connect to Server distant
```bash
ssh k8s-master
ssh k8s-worker
```

### If error
```
ssh k8s-master
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
IT IS POSSIBLE THAT SOMEONE IS DOING SOMETHING NASTY!
Someone could be eavesdropping on you right now (man-in-the-middle attack)!
It is also possible that a host key has just been changed.
The fingerprint for the ED25519 key sent by the remote host is
SHA256:/zhysT5zwjBcfCFRNJ5aj6LKmc0Lp5MkuqhdozCpTyE.
Please contact your system administrator.
Add correct host key in /Users/coumaranecouppane/.ssh/known_hosts to get rid of this message.
Offending ECDSA key in /Users/coumaranecouppane/.ssh/known_hosts:34
Host key for 193.70.35.121 has changed and you have requested strict checking.
Host key verification failed.
```

### Solution
```bash
ssh-keygen -R k8s-master
# OR, if k8s-master resolves to 193.70.35.121 and that's the specific IP you're connecting to
ssh-keygen -R 193.70.35.121


# Worker
ssh-keygen -R k8s-worker
# or
ssh-keygen -R 193.70.35.122
```
