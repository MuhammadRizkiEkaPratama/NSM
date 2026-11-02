# Encrypting LDAP with StartTLS

How the lab's LDAP traffic (passwords included) was moved from plaintext to
StartTLS with an internal CA, what had to change on each client, and how the
result was verified. Hosts, domain (`dc=bsp,dc=id`) and the CA name are lab
labels (see the [README](../README.md)). Step markers: `[manual]` = you do it on
the host or VM, `[script]` = a repo script does it.

## 1. Why this became a finding

The SSSD configuration carried this line from the start, and its name says it
all:

```
ldap_auth_disable_tls_never_use_in_production = true
```

While the directory shared a LAN with its clients, the exposure was one segment.
In the two-site topology ([TOPOLOGY](TOPOLOGY.md)) every web login and every SSH
login sends a password across the emulated ISP router, a stand-in for a carrier
device the organization does not own. Nobody edited a line, yet the risk changed:
**a topology change can turn a previously correct decision into a weakness.**

## 2. StartTLS on 389, not LDAPS on 636

| | |
|---|---|
| LDAPS `:636` | new port: new router ACL entry, new host firewall rule, one more thing to guard |
| **StartTLS `:389`** | same port; the session starts in clear and is **upgraded** before any credential is sent |

StartTLS adds no new surface (the inter-site ACL only permits 389 anyway). Its one
risk: a client that does not *require* it silently falls back to plaintext when
the server refuses. So every client is set to require it, not merely try it.

## 3. Internal CA

No public CA issues certificates for a private address such as `192.168.20.101`;
an internal CA is the normal practice, not a lab shortcut. What separates a sound
internal CA from a careless one: the CA's private key is protected (root-only,
never copied to clients; only the CA *certificate* is distributed) and clients
verify the chain instead of accepting anything.

- CA certificate: `bsp-lab-ca.crt` (subject `BSP Lab Internal CA`, a lab label),
  valid 10 years. Copy at the repo root and in `backend/`.
- Server certificate: 2 years. Lifetimes differ on purpose: a CA expiring with
  its leaf means two renewals on the same panicked day.
- The server certificate carries **SANs for both** `IP:192.168.20.101` and
  `DNS:nsm-ubuntu`; modern TLS stacks ignore the CN when matching hosts.

Server side `[manual]` (outline; the repo does not script certificate issuance):
issue the server certificate from the CA, then point `slapd` at the CA
certificate, server certificate and key with the `olcTLSCACertificateFile`,
`olcTLSCertificateFile` and `olcTLSCertificateKeyFile` attributes via
`ldapmodify` (on cn=config). The key must be readable by the `slapd` service
account only. Removing those `olcTLS*` attributes with `ldapmodify` is the
rollback.

## 4. Five parties, all must change

| Party | Setting |
|---|---|
| `sssd` on the web server | `ldap_id_use_start_tls = true`, `ldap_tls_reqcert = demand` |
| `sssd` on the data server | same |
| NSM Python (`ldap3`) | `AUTO_BIND_TLS_BEFORE_BIND` + `CERT_REQUIRED` (`backend/connectors/ldapdir.py`) |
| NSM Spring (Java) | `DefaultTlsDirContextAuthenticationStrategy` when the URL is `ldap://` (`LdapConfig.java`) |
| E-Canteen demo app (plain JNDI) | `StartTlsRequest` -> `negotiate()` -> only then credentials |

Any other `sssd` client needs the same two changes. Make the lab CA certificate
available to each `sssd` VM (for example in the system trust store, or via
`ldap_tls_cacert`); the repo does not record how this was done.

### Order matters

In `sssd`, **delete** the `ldap_auth_disable_tls_never_use_in_production` line;
enabling `ldap_id_use_start_tls` is not enough. While it exists, the
authentication path may stay plain even though the search path is encrypted, and
the authentication path carries the password. Two paths, two switches, and the
one with the longer name is the one that matters. (The sample
`ldap/sssd.conf` in the repo is the pre-TLS version.)

For the JNDI client, do not put the password in the environment table when
opening the context. JNDI would send it at connect time, before TLS is
negotiated:

```java
ctx = new InitialLdapContext(env, null);          // no credentials yet
tls = (StartTlsResponse) ctx.extendedOperation(new StartTlsRequest());
tls.negotiate();                                   // verifies the certificate
ctx.addToEnvironment(Context.SECURITY_CREDENTIALS, password);
ctx.reconnect(null);                               // bind, over TLS
```

NSM configuration `[manual]`:

- `backend/.env`: `LDAP_URL=ldap://192.168.20.101:389`, `LDAP_BASIS=dc=bsp,dc=id`
- `application.properties`: `nsm.ldap.url=ldap://192.168.20.101:389/dc=bsp,dc=id`
  (an `ldap://` URL turns StartTLS on; certificate checks are never bypassed)
- The Python reader refuses to connect at all if `backend/bsp-lab-ca.crt` is
  missing, rather than falling back to plaintext.

## 5. Two oddities

### 5.1 `ldap3` ignores IP-type SANs

`sssd` matches either SAN; `ldap3` uses a legacy matcher derived from
`ssl.match_hostname` (removed from Python) that reads only DNS-type SANs. The fix
is `valid_names=["nsm-ubuntu"]`. The chain is still fully verified against the lab
CA (`CERT_REQUIRED`); only certificates issued by that CA for that name are
accepted. With internal DNS you would connect by name and drop this.

### 5.2 The JDK `cacerts` is not writable without admin rights

Build a separate truststore: **a copy of the JDK `cacerts` plus the lab CA** (110
entries in the lab's JDK, not 1). A truststore containing only the lab CA makes
Java distrust every public CA and breaks unrelated things. Create it `[manual]`:
copy `%JAVA_HOME%\lib\security\cacerts` to `nsm-truststore.jks`, then import the
CA into the copy:

```
keytool -importcert -alias bsp-lab-ca -file bsp-lab-ca.crt -keystore nsm-truststore.jks -storepass <TRUSTSTORE_PASSWORD>
```

(`<TRUSTSTORE_PASSWORD>` is the password of the copied store.) `restart_nsm.ps1`
points Java at it through `JAVA_TOOL_OPTIONS`
(`-Djavax.net.ssl.trustStore=...`) and prints a red warning if the file is
missing. `*.jks` is git-ignored; do not commit it.

Symptom if the truststore is missing: `PKIX path building failed` in the Spring
log, while the login page just says "wrong username or password" for **every**
account, including correct passwords. Hours can be lost hunting for a password
that was never wrong.

## 6. Proof: sniff your own path

A test that only checks "login works" proves nothing about encryption; plaintext
logins work too. Look for what **should not exist**.

On the directory VM, capture to a **file** during real logins (streaming the output
over a flaky SSH session once captured 0 bytes, and "no password found" in an empty
capture proves nothing):

```
sudo timeout 120 tcpdump -i any -w /tmp/ldap.pcap 'tcp port 389'
```

Log in a few times as directory users, then analyse the capture (Wireshark or
`tshark`). Lab result: 3 real logins, 121 LDAP packets.

| Looked for | Result |
|---|---|
| a test password in cleartext | **absent** |
| the user DN (`uid=arif,ou=people,...`) | **absent** |
| a StartTLS extended request (OID `1.3.6.1.4.1.1466.20037`) | **present** |

The certificate is not visible in the capture either, which is reassuring: TLS
1.3 encrypts the certificate exchange. Negotiated parameters seen from a client
check: TLSv1.3, `TLS_AES_256_GCM_SHA384`, peer `O = BSP Lab, CN = nsm-ubuntu`,
verification OK.

## 7. Verification

| Test | Result |
|---|---|
| `ldapsearch -ZZ` (StartTLS **required**) on the directory VM | answers |
| `getent passwd arif` on the web and data servers | answers, via StartTLS |
| NSM Python reads the directory | 8 people (the lab's fictional users) |
| NSM Python **without the CA file** | refuses to connect, no silent plaintext |
| NSM Spring login | works |
| `backend/uji_ldap_ecanteen.py` (E-Canteen demo app) | 10/10, including wrong and empty passwords rejected |

## 8. Latency

StartTLS adds a full handshake. Measured on a quiet lab link with a deliberately
slow emulated WAN: socket open ~200 ms, StartTLS ~700 ms, bind ~400 ms, DN search
~180 ms, second session plus user bind ~1.2-1.3 s; a whole login took 2.5-3.0 s.
Timeouts in `application.properties` were raised accordingly
(`nsm.ldap.timeout-sambung-ms=5000`, `nsm.ldap.timeout-baca-ms=15000`). A timeout
that is too tight looks like "LDAP is down", not "slow".

## 9. Rollback

| Component | How |
|---|---|
| `sssd` | keep a copy of the pre-change config on each server (the lab used `sssd.conf.sebelum-tls`) |
| E-Canteen | keep the pre-change jar (`ecanteen.sebelum-tls.jar`) |
| `slapd` | remove the `olcTLS*` attributes with `ldapmodify` |

The `sssd` switch script should **prove before it commits and restore on failure**:
run `getent passwd <directory user>` after the change and put the old config back
automatically if the directory stops answering. Use a **local** account to run it,
so the way in to repair things is not cut by the thing being changed.

## 10. Limits

- Enforcement is on the **client** side. This guide does not show `slapd`
  refusing plaintext, and the repo's live test `uji_ldap_hidup.py` still binds on
  389 without StartTLS. If you want the server to enforce it, do that after every
  client is converted (for example `olcSecurity: tls=1`); the lab did not record
  doing so.
- Lifetimes are not automated: nothing renews the certificates.
- The CA and server certificates are lab artifacts for a private lab network.
