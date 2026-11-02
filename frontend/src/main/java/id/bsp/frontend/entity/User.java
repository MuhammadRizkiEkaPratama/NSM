package id.bsp.frontend.entity;

import jakarta.persistence.*;
import org.hibernate.annotations.ColumnDefault;
import java.time.LocalDateTime;

/**
 * NSM user account (`users` table in MySQL). Three states, hence `nonaktif` next to `enabled`:
 * pending (enabled=false, nonaktif=false), active (enabled=true), and deactivated
 * (enabled=false, nonaktif=true). Spring Security only checks `enabled`; the second flag keeps
 * revoked accounts from reappearing in the "pending approval" list.
 */
@Entity
@Table(name = "users")
public class User {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(unique = true, nullable = false)
    private String username;

    @Column(unique = true, nullable = false)
    private String email;

    @Column(nullable = false)
    private String password;

    // "ADMIN", "VIEWER", or "ADMIN_PLATFORM". Legacy "ADMIN" stays a tenant admin (confined to
    // its tenant) so the migration does not silently widen anyone's rights; cross-tenant access must
    // be granted deliberately.
    @Column(nullable = false)
    private String role;

    // Tenant that owns this account. NULL means no filtering (pre-multi-tenancy behavior), so
    // enabling multi-tenancy does not blank out existing accounts.
    @Column(name = "tenant_id")
    private Long tenantId;

    // false = pending (not yet approved by an admin), true = active
    @Column(nullable = false)
    private boolean enabled;

    @Column(nullable = false)
    @ColumnDefault("0")
    private boolean nonaktif = false;

    /**
     * Emergency account: may log in through MySQL when LDAP is unreachable. The flag does not make
     * the account a shortcut: while LDAP answers, its answer is used (even "wrong password").
     * Otherwise old accounts would become a permanent back door. Every use is logged prominently
     * in the audit log.
     */
    @Column(nullable = false)
    @ColumnDefault("0")
    private boolean darurat = false;

    @Column(name = "created_at")
    private LocalDateTime createdAt;

    @Column(name = "failed_attempts", nullable = false)
    @ColumnDefault("0")
    private int failedAttempts = 0;

    @Column(name = "locked_until")
    private LocalDateTime lockedUntil;

    // Fase 3b/3c — tingkat lockout: 0 normal, 1 pernah freeze, 2 email terkirim, 3 IP diblok.
    @Column(name = "lock_level", nullable = false)
    @ColumnDefault("0")
    private int lockLevel = 0;

    // --- getter & setter ---
    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }

    public String getUsername() { return username; }
    public void setUsername(String username) { this.username = username; }

    public String getEmail() { return email; }
    public void setEmail(String email) { this.email = email; }

    public String getPassword() { return password; }
    public void setPassword(String password) { this.password = password; }

    public String getRole() { return role; }
    public void setRole(String role) { this.role = role; }

    public Long getTenantId() { return tenantId; }
    public void setTenantId(Long tenantId) { this.tenantId = tenantId; }

    public static final String PERAN_PLATFORM = "ADMIN_PLATFORM";

    /**
     * Whether this account sees across tenants. Platform admins do not send the
     * `X-NSM-Tenant` header, so Python applies no tenant filter.
     */
    public boolean isAdminPlatform() {
        return PERAN_PLATFORM.equalsIgnoreCase(role);
    }

    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled = enabled; }

    public boolean isNonaktif() { return nonaktif; }
    public void setNonaktif(boolean nonaktif) { this.nonaktif = nonaktif; }

    public boolean isDarurat() { return darurat; }
    public void setDarurat(boolean darurat) { this.darurat = darurat; }

    public String getKeadaan() {
        if (enabled) return "AKTIF";
        return nonaktif ? "DINONAKTIFKAN" : "MENUNGGU";
    }

    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }

    public int getFailedAttempts() { return failedAttempts; }
    public void setFailedAttempts(int failedAttempts) { this.failedAttempts = failedAttempts; }

    public LocalDateTime getLockedUntil() { return lockedUntil; }
    public void setLockedUntil(LocalDateTime lockedUntil) { this.lockedUntil = lockedUntil; }

    public int getLockLevel() { return lockLevel; }
    public void setLockLevel(int lockLevel) { this.lockLevel = lockLevel; }
}
